#include <benchmark/benchmark.h>

#include <cstdint>
#include <string>
#include <vector>

#include "benchmark_common.h"

namespace {

constexpr std::int64_t kInstructionsPerBlock = 64;

struct InstructionMix {
  std::int64_t conversion_per_block;
  std::int64_t fma_per_block;
  std::int64_t integer_per_block;
};

constexpr InstructionMix kConvertIntegerMix{32, 0, 32};
constexpr InstructionMix kFmaIntegerMix{0, 32, 32};
constexpr InstructionMix kConvertFmaIntegerMix{16, 16, 32};

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

// Pair mixes use eight independent destinations per class. FMA destinations
// are true accumulator chains; conversion and integer destinations are renamed
// overwrites and therefore carry no loop-carried RAW dependency.
__attribute__((noinline)) void RunZmmConvertIntegerMix(int blocks) {
  asm volatile(
      "vpxord %%zmm28, %%zmm28, %%zmm28\n\t"
      "vpxord %%zmm29, %%zmm29, %%zmm29\n\t"
      ".p2align 5\n\t"
      "1:\n\t"
      ".rept 4\n\t"
      "vcvttps2dq %%zmm28, %%zmm0\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm8\n\t"
      "vcvttps2dq %%zmm28, %%zmm1\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm9\n\t"
      "vcvttps2dq %%zmm28, %%zmm2\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm10\n\t"
      "vcvttps2dq %%zmm28, %%zmm3\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm11\n\t"
      "vcvttps2dq %%zmm28, %%zmm4\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm12\n\t"
      "vcvttps2dq %%zmm28, %%zmm5\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm13\n\t"
      "vcvttps2dq %%zmm28, %%zmm6\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm14\n\t"
      "vcvttps2dq %%zmm28, %%zmm7\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm15\n\t"
      ".endr\n\t"
      "decl %[blocks]\n\t"
      "jne 1b\n\t"
      : [blocks] "+r"(blocks)
      :
      : "cc", "memory", "zmm0", "zmm1", "zmm2", "zmm3", "zmm4",
        "zmm5", "zmm6", "zmm7", "zmm8", "zmm9", "zmm10", "zmm11",
        "zmm12", "zmm13", "zmm14", "zmm15", "zmm28", "zmm29");
}

__attribute__((noinline)) void RunZmmFmaIntegerMix(int blocks) {
  asm volatile(
      "vpxord %%zmm28, %%zmm28, %%zmm28\n\t"
      "vpxord %%zmm29, %%zmm29, %%zmm29\n\t"
      "vpxord %%zmm0, %%zmm0, %%zmm0\n\t"
      "vpxord %%zmm1, %%zmm1, %%zmm1\n\t"
      "vpxord %%zmm2, %%zmm2, %%zmm2\n\t"
      "vpxord %%zmm3, %%zmm3, %%zmm3\n\t"
      "vpxord %%zmm4, %%zmm4, %%zmm4\n\t"
      "vpxord %%zmm5, %%zmm5, %%zmm5\n\t"
      "vpxord %%zmm6, %%zmm6, %%zmm6\n\t"
      "vpxord %%zmm7, %%zmm7, %%zmm7\n\t"
      ".p2align 5\n\t"
      "1:\n\t"
      ".rept 4\n\t"
      "vfmadd231ps %%zmm28, %%zmm29, %%zmm0\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm8\n\t"
      "vfmadd231ps %%zmm28, %%zmm29, %%zmm1\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm9\n\t"
      "vfmadd231ps %%zmm28, %%zmm29, %%zmm2\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm10\n\t"
      "vfmadd231ps %%zmm28, %%zmm29, %%zmm3\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm11\n\t"
      "vfmadd231ps %%zmm28, %%zmm29, %%zmm4\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm12\n\t"
      "vfmadd231ps %%zmm28, %%zmm29, %%zmm5\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm13\n\t"
      "vfmadd231ps %%zmm28, %%zmm29, %%zmm6\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm14\n\t"
      "vfmadd231ps %%zmm28, %%zmm29, %%zmm7\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm15\n\t"
      ".endr\n\t"
      "decl %[blocks]\n\t"
      "jne 1b\n\t"
      : [blocks] "+r"(blocks)
      :
      : "cc", "memory", "zmm0", "zmm1", "zmm2", "zmm3", "zmm4",
        "zmm5", "zmm6", "zmm7", "zmm8", "zmm9", "zmm10", "zmm11",
        "zmm12", "zmm13", "zmm14", "zmm15", "zmm28", "zmm29");
}

// The 1:1:2 ratio lets conversion and FMA jointly saturate a two-lane shared
// domain while integer operations simultaneously probe two additional lanes.
__attribute__((noinline)) void RunZmmConvertFmaIntegerMix(int blocks) {
  asm volatile(
      "vpxord %%zmm28, %%zmm28, %%zmm28\n\t"
      "vpxord %%zmm29, %%zmm29, %%zmm29\n\t"
      "vpxord %%zmm4, %%zmm4, %%zmm4\n\t"
      "vpxord %%zmm5, %%zmm5, %%zmm5\n\t"
      "vpxord %%zmm6, %%zmm6, %%zmm6\n\t"
      "vpxord %%zmm7, %%zmm7, %%zmm7\n\t"
      ".p2align 5\n\t"
      "1:\n\t"
      ".rept 4\n\t"
      "vcvttps2dq %%zmm28, %%zmm0\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm8\n\t"
      "vfmadd231ps %%zmm28, %%zmm29, %%zmm4\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm9\n\t"
      "vcvttps2dq %%zmm28, %%zmm1\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm10\n\t"
      "vfmadd231ps %%zmm28, %%zmm29, %%zmm5\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm11\n\t"
      "vcvttps2dq %%zmm28, %%zmm2\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm12\n\t"
      "vfmadd231ps %%zmm28, %%zmm29, %%zmm6\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm13\n\t"
      "vcvttps2dq %%zmm28, %%zmm3\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm14\n\t"
      "vfmadd231ps %%zmm28, %%zmm29, %%zmm7\n\t"
      "vpaddd %%zmm28, %%zmm29, %%zmm15\n\t"
      ".endr\n\t"
      "decl %[blocks]\n\t"
      "jne 1b\n\t"
      : [blocks] "+r"(blocks)
      :
      : "cc", "memory", "zmm0", "zmm1", "zmm2", "zmm3", "zmm4",
        "zmm5", "zmm6", "zmm7", "zmm8", "zmm9", "zmm10", "zmm11",
        "zmm12", "zmm13", "zmm14", "zmm15", "zmm28", "zmm29");
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

void RunZmmContentionBenchmark(benchmark::State& state, Kernel kernel,
                               const InstructionMix& mix) {
  const int blocks = static_cast<int>(state.range(0));
  auto events = amd_profile::PerfEventGroup::Open({
      amd_profile::CoreCycles(),
      amd_profile::RawEvent("retired_zmm_ops", 0x08, 0x20),
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

  const double executed_blocks =
      static_cast<double>(state.iterations()) * blocks;
  const double conversion = executed_blocks * mix.conversion_per_block;
  const double fma = executed_blocks * mix.fma_per_block;
  const double integer = executed_blocks * mix.integer_per_block;
  const double instructions = conversion + fma + integer;
  const double source_operands = conversion + 3.0 * fma + 2.0 * integer;
  const double cycles = amd_profile::FindEvent(values, "core_cycles");
  const double retired_zmm =
      amd_profile::FindEvent(values, "retired_zmm_ops");
  const double fp_dispatch =
      amd_profile::FindEvent(values, "fp_dispatch_ops");

  state.counters["target_instructions"] = instructions;
  state.counters["conversion_target_instructions"] = conversion;
  state.counters["fma_target_instructions"] = fma;
  state.counters["integer_target_instructions"] = integer;
  state.counters["static_source_operands"] = source_operands;
  state.counters["static_source_operands_per_instruction"] =
      source_operands / instructions;
  state.counters["static_source_operands_per_cycle"] =
      source_operands / cycles;
  state.counters["conversion_share"] = conversion / instructions;
  state.counters["fma_share"] = fma / instructions;
  state.counters["integer_share"] = integer / instructions;
  state.counters["conversion_instructions_per_cycle"] = conversion / cycles;
  state.counters["fma_instructions_per_cycle"] = fma / cycles;
  state.counters["integer_instructions_per_cycle"] = integer / cycles;
  state.counters["mixed_instructions_per_cycle"] = instructions / cycles;
  state.counters["cycles_per_instruction"] = cycles / instructions;
  state.counters["retired_zmm_ops_per_target"] = retired_zmm / instructions;
  state.counters["fp_dispatch_ops_per_target"] = fp_dispatch / instructions;
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

#define DEFINE_ZMM_BENCHMARK(name, kernel, mix)                               \
  void name(benchmark::State& state) {                                        \
    RunZmmContentionBenchmark(state, kernel, mix);                            \
  }                                                                           \
  BENCHMARK(name)->Arg(4096)->Iterations(5)

DEFINE_ZMM_BENCHMARK(BM_ContentionZmmConvertInteger1To1,
                     RunZmmConvertIntegerMix, kConvertIntegerMix);
DEFINE_ZMM_BENCHMARK(BM_ContentionZmmFmaInteger1To1, RunZmmFmaIntegerMix,
                     kFmaIntegerMix);
DEFINE_ZMM_BENCHMARK(BM_ContentionZmmConvertFmaInteger1To1To2,
                     RunZmmConvertFmaIntegerMix, kConvertFmaIntegerMix);

#undef DEFINE_ZMM_BENCHMARK

}  // namespace
