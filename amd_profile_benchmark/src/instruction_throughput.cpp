#include <benchmark/benchmark.h>

#include <cstdint>
#include <string>
#include <vector>

#include "benchmark_common.h"

namespace {

constexpr std::int64_t kInstructionsPerBlock = 64;

#define ADD8(reg)                                                             \
  "vaddps %%" reg "16, %%" reg "0, %%" reg "0\n\t"                    \
  "vaddps %%" reg "16, %%" reg "1, %%" reg "1\n\t"                    \
  "vaddps %%" reg "16, %%" reg "2, %%" reg "2\n\t"                    \
  "vaddps %%" reg "16, %%" reg "3, %%" reg "3\n\t"                    \
  "vaddps %%" reg "16, %%" reg "4, %%" reg "4\n\t"                    \
  "vaddps %%" reg "16, %%" reg "5, %%" reg "5\n\t"                    \
  "vaddps %%" reg "16, %%" reg "6, %%" reg "6\n\t"                    \
  "vaddps %%" reg "16, %%" reg "7, %%" reg "7\n\t"

#define DEFINE_ADD_THROUGHPUT_KERNEL(name, reg)                              \
  __attribute__((noinline)) void name(int blocks) {                          \
    asm volatile("vpxord %%zmm16, %%zmm16, %%zmm16\n\t"                   \
                 "1:\n\t"                                                   \
                 ".rept 8\n\t"                                              \
                 ADD8(reg)                                                   \
                 ".endr\n\t"                                                \
                 "decl %[blocks]\n\t"                                       \
                 "jne 1b\n\t"                                               \
                 : [blocks] "+r"(blocks)                                    \
                 :                                                           \
                 : "cc", "memory", "zmm0", "zmm1", "zmm2", "zmm3", \
                   "zmm4", "zmm5", "zmm6", "zmm7", "zmm16");          \
  }

DEFINE_ADD_THROUGHPUT_KERNEL(RunXmmAddThroughput, "xmm")
DEFINE_ADD_THROUGHPUT_KERNEL(RunYmmAddThroughput, "ymm")
DEFINE_ADD_THROUGHPUT_KERNEL(RunZmmAddThroughput, "zmm")

#undef DEFINE_ADD_THROUGHPUT_KERNEL
#undef ADD8

#define VECTOR_OP8(op, reg)                                                   \
  op " %%" reg "16, %%" reg "17, %%" reg "0\n\t"                        \
  op " %%" reg "16, %%" reg "17, %%" reg "1\n\t"                        \
  op " %%" reg "16, %%" reg "17, %%" reg "2\n\t"                        \
  op " %%" reg "16, %%" reg "17, %%" reg "3\n\t"                        \
  op " %%" reg "16, %%" reg "17, %%" reg "4\n\t"                        \
  op " %%" reg "16, %%" reg "17, %%" reg "5\n\t"                        \
  op " %%" reg "16, %%" reg "17, %%" reg "6\n\t"                        \
  op " %%" reg "16, %%" reg "17, %%" reg "7\n\t"

#define DEFINE_THREE_OPERAND_KERNEL(name, op, reg)                           \
  __attribute__((noinline)) void name(int blocks) {                          \
    asm volatile("vpxord %%zmm16, %%zmm16, %%zmm16\n\t"                   \
                 "vpxord %%zmm17, %%zmm17, %%zmm17\n\t"                   \
                 "1:\n\t"                                                   \
                 ".rept 8\n\t"                                              \
                 VECTOR_OP8(op, reg)                                         \
                 ".endr\n\t"                                                \
                 "decl %[blocks]\n\t"                                       \
                 "jne 1b\n\t"                                               \
                 : [blocks] "+r"(blocks)                                    \
                 :                                                           \
                 : "cc", "memory", "zmm0", "zmm1", "zmm2", "zmm3", \
                   "zmm4", "zmm5", "zmm6", "zmm7", "zmm16",         \
                   "zmm17");                                                \
  }

DEFINE_THREE_OPERAND_KERNEL(RunYmmFmaThroughput, "vfmadd231ps", "ymm")
DEFINE_THREE_OPERAND_KERNEL(RunYmmIntegerThroughput, "vpaddd", "ymm")
DEFINE_THREE_OPERAND_KERNEL(RunYmmShuffleThroughput, "vpermps", "ymm")
DEFINE_THREE_OPERAND_KERNEL(RunZmmFmaThroughput, "vfmadd231ps", "zmm")
DEFINE_THREE_OPERAND_KERNEL(RunZmmIntegerThroughput, "vpaddd", "zmm")

#undef DEFINE_THREE_OPERAND_KERNEL
#undef VECTOR_OP8

__attribute__((noinline)) void RunYmmConvertThroughput(int blocks) {
  asm volatile(
      "vpxord %%zmm16, %%zmm16, %%zmm16\n\t"
      "1:\n\t"
      ".rept 8\n\t"
      "vcvtps2dq %%ymm16, %%ymm0\n\t"
      "vcvtps2dq %%ymm16, %%ymm1\n\t"
      "vcvtps2dq %%ymm16, %%ymm2\n\t"
      "vcvtps2dq %%ymm16, %%ymm3\n\t"
      "vcvtps2dq %%ymm16, %%ymm4\n\t"
      "vcvtps2dq %%ymm16, %%ymm5\n\t"
      "vcvtps2dq %%ymm16, %%ymm6\n\t"
      "vcvtps2dq %%ymm16, %%ymm7\n\t"
      ".endr\n\t"
      "decl %[blocks]\n\t"
      "jne 1b\n\t"
      : [blocks] "+r"(blocks)
      :
      : "cc", "memory", "zmm0", "zmm1", "zmm2", "zmm3", "zmm4",
        "zmm5", "zmm6", "zmm7", "zmm16");
}

__attribute__((noinline)) void RunZmmTruncateConvertThroughput(int blocks) {
  asm volatile(
      "vpxord %%zmm16, %%zmm16, %%zmm16\n\t"
      "1:\n\t"
      ".rept 8\n\t"
      "vcvttps2dq %%zmm16, %%zmm0\n\t"
      "vcvttps2dq %%zmm16, %%zmm1\n\t"
      "vcvttps2dq %%zmm16, %%zmm2\n\t"
      "vcvttps2dq %%zmm16, %%zmm3\n\t"
      "vcvttps2dq %%zmm16, %%zmm4\n\t"
      "vcvttps2dq %%zmm16, %%zmm5\n\t"
      "vcvttps2dq %%zmm16, %%zmm6\n\t"
      "vcvttps2dq %%zmm16, %%zmm7\n\t"
      ".endr\n\t"
      "decl %[blocks]\n\t"
      "jne 1b\n\t"
      : [blocks] "+r"(blocks)
      :
      : "cc", "memory", "zmm0", "zmm1", "zmm2", "zmm3", "zmm4",
        "zmm5", "zmm6", "zmm7", "zmm16");
}

using Kernel = void (*)(int);

void RunThroughputBenchmark(benchmark::State& state, Kernel kernel,
                            std::uint8_t width_mask) {
  const int blocks = static_cast<int>(state.range(0));
  auto events = amd_profile::PerfEventGroup::Open({
      amd_profile::CoreCycles(),
      amd_profile::RawEvent("retired_width_ops", 0x08, width_mask),
      amd_profile::RawEvent("retired_macro_ops", 0xc1, 0x00),
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
  state.counters["instructions_per_cycle"] = instructions / cycles;
  state.counters["issue_interval_cycles"] = cycles / instructions;
}

#define DEFINE_BENCHMARK(name, kernel, mask)                                  \
  void name(benchmark::State& state) {                                        \
    RunThroughputBenchmark(state, kernel, mask);                              \
  }                                                                           \
  BENCHMARK(name)->Arg(4096)->Iterations(5)

DEFINE_BENCHMARK(BM_VaddpsThroughputXmm, RunXmmAddThroughput, 0x08);
DEFINE_BENCHMARK(BM_VaddpsThroughputYmm, RunYmmAddThroughput, 0x10);
DEFINE_BENCHMARK(BM_VaddpsThroughputZmm, RunZmmAddThroughput, 0x20);
DEFINE_BENCHMARK(BM_VfmaddpsThroughputYmm, RunYmmFmaThroughput, 0x10);
DEFINE_BENCHMARK(BM_VpadddThroughputYmm, RunYmmIntegerThroughput, 0x10);
DEFINE_BENCHMARK(BM_VpermpsThroughputYmm, RunYmmShuffleThroughput, 0x10);
DEFINE_BENCHMARK(BM_Vcvtps2dqThroughputYmm, RunYmmConvertThroughput, 0x10);
DEFINE_BENCHMARK(BM_VfmaddpsThroughputZmm, RunZmmFmaThroughput, 0x20);
DEFINE_BENCHMARK(BM_VpadddThroughputZmm, RunZmmIntegerThroughput, 0x20);
DEFINE_BENCHMARK(BM_Vcvttps2dqThroughputZmm,
                 RunZmmTruncateConvertThroughput, 0x20);

#undef DEFINE_BENCHMARK

}  // namespace
