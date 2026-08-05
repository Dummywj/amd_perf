#include <benchmark/benchmark.h>
#include <sys/mman.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <numeric>
#include <random>
#include <string>
#include <vector>

#include "benchmark_common.h"

namespace {

struct alignas(64) Node {
  Node* next;
  std::byte padding[56];
};
static_assert(sizeof(Node) == 64);

Node* BuildRandomCycle(amd_profile::AlignedBuffer<Node>* nodes) {
  std::vector<std::size_t> order(nodes->size());
  std::iota(order.begin(), order.end(), 0);
  std::mt19937_64 random(0x5a17d3ULL + nodes->size());
  std::shuffle(order.begin(), order.end(), random);
  for (std::size_t i = 0; i < order.size(); ++i) {
    (*nodes)[order[i]].next = &(*nodes)[order[(i + 1) % order.size()]];
  }
  return &(*nodes)[order[0]];
}

__attribute__((noinline)) Node* Chase(Node* current, std::size_t steps) {
  for (std::size_t i = 0; i < steps; ++i) {
    current = current->next;
  }
  return current;
}

void BM_CacheLatency(benchmark::State& state) {
  const std::size_t bytes = static_cast<std::size_t>(state.range(0));
  const std::size_t steps = static_cast<std::size_t>(state.range(1));
  amd_profile::AlignedBuffer<Node> nodes(bytes / sizeof(Node));
  (void)madvise(nodes.data(), bytes, MADV_HUGEPAGE);
  Node* current = BuildRandomCycle(&nodes);
  current = Chase(current, nodes.size());
  benchmark::DoNotOptimize(current);

  auto events = amd_profile::PerfEventGroup::Open({
      amd_profile::CoreCycles(),
      amd_profile::RawEvent("l2_demand_misses", 0x64, 0x08),
      amd_profile::RawEvent("local_dram_fills", 0x43, 0x08),
  });
  std::string error;
  if (!amd_profile::StartEvents(state, &events, &error)) {
    return;
  }
  for (auto _ : state) {
    benchmark::DoNotOptimize(_);
    current = Chase(current, steps);
  }
  benchmark::DoNotOptimize(current);
  std::vector<amd_profile::EventValue> values;
  if (!amd_profile::StopEvents(state, &events, &values, &error)) {
    return;
  }

  const double loads = static_cast<double>(state.iterations()) * steps;
  const double cycles = amd_profile::FindEvent(values, "core_cycles");
  state.SetItemsProcessed(static_cast<std::int64_t>(loads));
  state.counters["working_set_bytes"] = static_cast<double>(bytes);
  state.counters["dependent_loads"] = loads;
  state.counters["latency_cycles"] = cycles / loads;
  state.counters["l2_misses_per_load"] =
      amd_profile::FindEvent(values, "l2_demand_misses") / loads;
  state.counters["dram_fills_per_load"] =
      amd_profile::FindEvent(values, "local_dram_fills") / loads;
}

void RegisterCacheLatency(const char* name, std::int64_t bytes,
                          std::int64_t steps) {
  benchmark::RegisterBenchmark(name, BM_CacheLatency)
      ->Args({bytes, steps})
      ->Iterations(1);
}

const bool kRegistered = [] {
  RegisterCacheLatency("CacheLatency/L1D", 16LL << 10, 8LL << 20);
  RegisterCacheLatency("CacheLatency/L2", 256LL << 10, 8LL << 20);
  RegisterCacheLatency("CacheLatency/L3", 4LL << 20, 2LL << 20);
  RegisterCacheLatency("CacheLatency/DRAM", 256LL << 20, 1LL << 20);
  return true;
}();

}  // namespace
