#include <benchmark/benchmark.h>

#include <cstdint>
#include <string>
#include <vector>

#include "benchmark_common.h"

namespace {

constexpr std::int64_t kInstructionsPerBlock = 64;

#define DEFINE_MIXED_KERNEL(name, second_op)                                  \
  __attribute__((noinline)) void name(int blocks) {                          \
    asm volatile("vpxord %%zmm16, %%zmm16, %%zmm16\n\t"                   \
                 "vpxord %%zmm17, %%zmm17, %%zmm17\n\t"                   \
                 "1:\n\t"                                                   \
                 ".rept 8\n\t"                                              \
                 "vaddps %%ymm16, %%ymm0, %%ymm0\n\t"                    \
                 second_op " %%ymm16, %%ymm17, %%ymm4\n\t"                  \
                 "vaddps %%ymm16, %%ymm1, %%ymm1\n\t"                    \
                 second_op " %%ymm16, %%ymm17, %%ymm5\n\t"                  \
                 "vaddps %%ymm16, %%ymm2, %%ymm2\n\t"                    \
                 second_op " %%ymm16, %%ymm17, %%ymm6\n\t"                  \
                 "vaddps %%ymm16, %%ymm3, %%ymm3\n\t"                    \
                 second_op " %%ymm16, %%ymm17, %%ymm7\n\t"                  \
                 ".endr\n\t"                                                \
                 "decl %[blocks]\n\t"                                       \
                 "jne 1b\n\t"                                               \
                 : [blocks] "+r"(blocks)                                    \
                 :                                                           \
                 : "cc", "memory", "zmm0", "zmm1", "zmm2", "zmm3", \
                   "zmm4", "zmm5", "zmm6", "zmm7", "zmm16",         \
                   "zmm17");                                                \
  }

DEFINE_MIXED_KERNEL(RunAddFmaMix, "vfmadd231ps")
DEFINE_MIXED_KERNEL(RunAddIntegerMix, "vpaddd")
DEFINE_MIXED_KERNEL(RunAddShuffleMix, "vpermps")

#undef DEFINE_MIXED_KERNEL

__attribute__((noinline)) void RunAddConvertMix(int blocks) {
  asm volatile(
      "vpxord %%zmm16, %%zmm16, %%zmm16\n\t"
      "1:\n\t"
      ".rept 8\n\t"
      "vaddps %%ymm16, %%ymm0, %%ymm0\n\t"
      "vcvtps2dq %%ymm16, %%ymm4\n\t"
      "vaddps %%ymm16, %%ymm1, %%ymm1\n\t"
      "vcvtps2dq %%ymm16, %%ymm5\n\t"
      "vaddps %%ymm16, %%ymm2, %%ymm2\n\t"
      "vcvtps2dq %%ymm16, %%ymm6\n\t"
      "vaddps %%ymm16, %%ymm3, %%ymm3\n\t"
      "vcvtps2dq %%ymm16, %%ymm7\n\t"
      ".endr\n\t"
      "decl %[blocks]\n\t"
      "jne 1b\n\t"
      : [blocks] "+r"(blocks)
      :
      : "cc", "memory", "zmm0", "zmm1", "zmm2", "zmm3", "zmm4",
        "zmm5", "zmm6", "zmm7", "zmm16");
}

using Kernel = void (*)(int);

void RunContentionBenchmark(benchmark::State& state, Kernel kernel) {
  const int blocks = static_cast<int>(state.range(0));
  auto events = amd_profile::PerfEventGroup::Open({
      amd_profile::CoreCycles(),
      amd_profile::RawEvent("retired_256_ops", 0x08, 0x10),
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
  state.counters["mixed_instructions_per_cycle"] = instructions / cycles;
  state.counters["cycles_per_instruction"] = cycles / instructions;
}

#define DEFINE_BENCHMARK(name, kernel)                                        \
  void name(benchmark::State& state) {                                        \
    RunContentionBenchmark(state, kernel);                                   \
  }                                                                           \
  BENCHMARK(name)->Arg(4096)->Iterations(5)

DEFINE_BENCHMARK(BM_ContentionAddFma, RunAddFmaMix);
DEFINE_BENCHMARK(BM_ContentionAddInteger, RunAddIntegerMix);
DEFINE_BENCHMARK(BM_ContentionAddShuffle, RunAddShuffleMix);
DEFINE_BENCHMARK(BM_ContentionAddConvert, RunAddConvertMix);

#undef DEFINE_BENCHMARK

}  // namespace
