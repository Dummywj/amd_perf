#include <benchmark/benchmark.h>

#include <cstdint>
#include <string>
#include <vector>

#include "benchmark_common.h"

namespace {

constexpr std::int64_t kNopsPerBlock = 192;
constexpr std::int64_t kLoopOpsPerBlock = 2;

__attribute__((noinline)) void RunNopStream(int blocks) {
  asm volatile(
      "1:\n\t"
      ".rept 192\n\t"
      "nop\n\t"
      ".endr\n\t"
      "decl %[blocks]\n\t"
      "jne 1b\n\t"
      : [blocks] "+r"(blocks)
      :
      : "cc", "memory");
}

void BM_PipelineWidth(benchmark::State& state) {
  const int blocks = static_cast<int>(state.range(0));
  auto events = amd_profile::PerfEventGroup::Open({
      amd_profile::CoreCycles(),
      amd_profile::RawEvent("retired_macro_ops", 0xc1, 0x00),
      amd_profile::RawEvent("retire_token_stall_cycles", 0xaf, 0x20),
  });
  std::string error;
  if (!amd_profile::StartEvents(state, &events, &error)) {
    return;
  }
  for (auto _ : state) {
    benchmark::DoNotOptimize(_);
    RunNopStream(blocks);
  }
  std::vector<amd_profile::EventValue> values;
  if (!amd_profile::StopEvents(state, &events, &values, &error)) {
    return;
  }

  const double cycles = amd_profile::FindEvent(values, "core_cycles");
  const double retired = amd_profile::FindEvent(values, "retired_macro_ops");
  const double static_instructions =
      static_cast<double>(state.iterations()) * blocks *
      (kNopsPerBlock + kLoopOpsPerBlock);
  state.counters["static_instructions"] = static_instructions;
  state.counters["retired_ops_per_cycle"] = retired / cycles;
  state.counters["static_to_retired_ratio"] = static_instructions / retired;
}

}  // namespace

BENCHMARK(BM_PipelineWidth)->Arg(4096)->Iterations(10);
