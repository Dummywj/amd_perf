#include <benchmark/benchmark.h>
#include <sys/mman.h>

#include <algorithm>
#include <array>
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

constexpr std::size_t kMaxStreams = 64;

void BuildStreamCycles(amd_profile::AlignedBuffer<Node>* nodes,
                       std::size_t streams,
                       std::array<Node*, kMaxStreams>* heads) {
  const std::size_t lines_per_stream = nodes->size() / streams;
  std::mt19937_64 random(0x9e3779b97f4a7c15ULL + nodes->size() + streams);
  for (std::size_t stream = 0; stream < streams; ++stream) {
    const std::size_t begin = stream * lines_per_stream;
    std::vector<std::size_t> order(lines_per_stream);
    std::iota(order.begin(), order.end(), begin);
    std::shuffle(order.begin(), order.end(), random);
    for (std::size_t i = 0; i < order.size(); ++i) {
      (*nodes)[order[i]].next = &(*nodes)[order[(i + 1) % order.size()]];
    }
    (*heads)[stream] = &(*nodes)[order[0]];
  }
}

template <std::size_t Streams>
__attribute__((noinline)) void ChaseStreams(
    std::array<Node*, kMaxStreams>* all_heads, std::size_t total_steps) {
  std::array<Node*, Streams> heads{};
  for (std::size_t i = 0; i < Streams; ++i) {
    heads[i] = (*all_heads)[i];
  }
  const std::size_t rounds = total_steps / Streams;
  for (std::size_t round = 0; round < rounds; ++round) {
#pragma GCC unroll 32
    for (std::size_t stream = 0; stream < Streams; ++stream) {
      heads[stream] = heads[stream]->next;
    }
  }
  for (std::size_t i = 0; i < Streams; ++i) {
    (*all_heads)[i] = heads[i];
  }
  benchmark::DoNotOptimize(all_heads->data());
}

void RunStreams(std::size_t streams,
                std::array<Node*, kMaxStreams>* heads,
                std::size_t total_steps) {
  switch (streams) {
    case 1: ChaseStreams<1>(heads, total_steps); break;
    case 2: ChaseStreams<2>(heads, total_steps); break;
    case 4: ChaseStreams<4>(heads, total_steps); break;
    case 8: ChaseStreams<8>(heads, total_steps); break;
    case 12: ChaseStreams<12>(heads, total_steps); break;
    case 16: ChaseStreams<16>(heads, total_steps); break;
    case 24: ChaseStreams<24>(heads, total_steps); break;
    case 32: ChaseStreams<32>(heads, total_steps); break;
    case 48: ChaseStreams<48>(heads, total_steps); break;
    case 64: ChaseStreams<64>(heads, total_steps); break;
    default: std::abort();
  }
}

void BM_MemoryParallelism(benchmark::State& state) {
  const std::size_t bytes = static_cast<std::size_t>(state.range(0));
  const std::size_t total_steps = static_cast<std::size_t>(state.range(1));
  const std::size_t streams = static_cast<std::size_t>(state.range(2));
  amd_profile::AlignedBuffer<Node> nodes(bytes / sizeof(Node));
  (void)madvise(nodes.data(), bytes, MADV_HUGEPAGE);
  std::array<Node*, kMaxStreams> heads{};
  BuildStreamCycles(&nodes, streams, &heads);
  RunStreams(streams, &heads, nodes.size());

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
    RunStreams(streams, &heads, total_steps);
  }
  std::vector<amd_profile::EventValue> values;
  if (!amd_profile::StopEvents(state, &events, &values, &error)) {
    return;
  }

  const double loads = static_cast<double>(state.iterations()) *
                       (total_steps / streams) * streams;
  const double cycles = amd_profile::FindEvent(values, "core_cycles");
  state.SetItemsProcessed(static_cast<std::int64_t>(loads));
  state.counters["working_set_bytes"] = static_cast<double>(bytes);
  state.counters["streams"] = static_cast<double>(streams);
  state.counters["loads_per_cycle"] = loads / cycles;
  state.counters["cycles_per_load"] = cycles / loads;
  state.counters["l2_misses_per_load"] =
      amd_profile::FindEvent(values, "l2_demand_misses") / loads;
  state.counters["dram_fills_per_load"] =
      amd_profile::FindEvent(values, "local_dram_fills") / loads;
}

void RegisterParallelismLevel(const char* level, std::int64_t bytes,
                              std::int64_t steps) {
  const std::array<int, 10> streams = {1, 2, 4, 8, 12,
                                       16, 24, 32, 48, 64};
  const std::string name = std::string("MemoryParallelism/") + level;
  auto* benchmark =
      benchmark::RegisterBenchmark(name.c_str(), BM_MemoryParallelism);
  for (int value : streams) {
    benchmark->Args({bytes, steps, value});
  }
  benchmark->Iterations(1);
}

const bool kRegistered = [] {
  RegisterParallelismLevel("L1D_miss_to_L2", 256LL << 10, 8LL << 20);
  RegisterParallelismLevel("L2_miss_to_L3", 4LL << 20, 2LL << 20);
  RegisterParallelismLevel("L3_miss_to_DRAM", 256LL << 20, 1LL << 20);
  return true;
}();

}  // namespace
