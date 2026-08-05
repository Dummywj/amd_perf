#include <benchmark/benchmark.h>

#include <cstdint>
#include <string>
#include <vector>

#include "benchmark_common.h"

namespace {

constexpr std::int64_t kInstructionsPerBlock = 64;

#define DEFINE_ADD_LATENCY_KERNEL(name, reg)                                 \
  __attribute__((noinline)) void name(int blocks) {                          \
    asm volatile("vxorps %%" reg "0, %%" reg "0, %%" reg "0\n\t"       \
                 "vxorps %%" reg "1, %%" reg "1, %%" reg "1\n\t"       \
                 "1:\n\t"                                                   \
                 ".rept 64\n\t"                                             \
                 "vaddps %%" reg "1, %%" reg "0, %%" reg "0\n\t"       \
                 ".endr\n\t"                                                \
                 "decl %[blocks]\n\t"                                       \
                 "jne 1b\n\t"                                               \
                 : [blocks] "+r"(blocks)                                    \
                 :                                                           \
                 : "cc", "memory", "zmm0", "zmm1");                     \
  }

DEFINE_ADD_LATENCY_KERNEL(RunXmmAddLatency, "xmm")
DEFINE_ADD_LATENCY_KERNEL(RunYmmAddLatency, "ymm")
DEFINE_ADD_LATENCY_KERNEL(RunZmmAddLatency, "zmm")

#undef DEFINE_ADD_LATENCY_KERNEL

using Kernel = void (*)(int);

void RunLatencyBenchmark(benchmark::State& state, Kernel kernel,
                         std::uint8_t width_mask) {
  const int blocks = static_cast<int>(state.range(0));
  auto events = amd_profile::PerfEventGroup::Open({
      amd_profile::CoreCycles(),
      amd_profile::RawEvent("retired_width_ops", 0x08, width_mask),
      amd_profile::RawEvent("fp_dispatch_ops", 0xab, 0x04),
  });
  std::string error;
  if (!amd_profile::StartEvents(state, &events, &error)) {
    return;
  }
  for (auto _ : state) {
    benchmark::DoNotOptimize(_);
    kernel(blocks);
  }
  std::vector<amd_profile::EventValue> values;
  if (!amd_profile::StopEvents(state, &events, &values, &error)) {
    return;
  }
  const double instructions = static_cast<double>(state.iterations()) *
                              blocks * kInstructionsPerBlock;
  const double cycles = amd_profile::FindEvent(values, "core_cycles");
  state.counters["target_instructions"] = instructions;
  state.counters["latency_cycles"] = cycles / instructions;
}

void BM_VaddpsLatencyXmm(benchmark::State& state) {
  RunLatencyBenchmark(state, RunXmmAddLatency, 0x08);
}

void BM_VaddpsLatencyYmm(benchmark::State& state) {
  RunLatencyBenchmark(state, RunYmmAddLatency, 0x10);
}

void BM_VaddpsLatencyZmm(benchmark::State& state) {
  RunLatencyBenchmark(state, RunZmmAddLatency, 0x20);
}

}  // namespace

BENCHMARK(BM_VaddpsLatencyXmm)->Arg(4096)->Iterations(5);
BENCHMARK(BM_VaddpsLatencyYmm)->Arg(4096)->Iterations(5);
BENCHMARK(BM_VaddpsLatencyZmm)->Arg(4096)->Iterations(5);
