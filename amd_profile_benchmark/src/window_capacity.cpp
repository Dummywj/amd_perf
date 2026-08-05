#include <benchmark/benchmark.h>
#include <immintrin.h>
#include <x86intrin.h>

#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "benchmark_common.h"

namespace {

alignas(64) std::array<std::uint64_t, 8> g_line_a{};
alignas(64) std::array<std::uint64_t, 8> g_line_b{};
alignas(64) std::array<std::uint64_t, 8> g_target{};

std::uint64_t ReadTscStart() {
  _mm_lfence();
  return __rdtsc();
}

std::uint64_t ReadTscEnd() {
  unsigned aux = 0;
  const std::uint64_t value = __rdtscp(&aux);
  _mm_lfence();
  return value;
}

void FlushProbeLines() {
  _mm_clflush(g_line_a.data());
  _mm_clflush(g_line_b.data());
  _mm_mfence();
}

std::uint64_t MeasureRobWindow(int blocks) {
  FlushProbeLines();
  const std::uint64_t start = ReadTscStart();
  asm volatile(
      "movq (%[a]), %%r8\n\t"
      "1:\n\t"
      ".rept 8\n\t"
      "movq %%r10, %%r11\n\t"
      "movq %%r11, %%r10\n\t"
      ".endr\n\t"
      "decl %[blocks]\n\t"
      "jne 1b\n\t"
      "movq (%[b]), %%r9\n\t"
      "addq %%r9, %%r8\n\t"
      : [blocks] "+r"(blocks)
      : [a] "r"(g_line_a.data()), [b] "r"(g_line_b.data())
      : "cc", "memory", "r8", "r9", "r10", "r11");
  return ReadTscEnd() - start;
}

std::uint64_t MeasureVectorScheduler(int blocks) {
  FlushProbeLines();
  const std::uint64_t start = ReadTscStart();
  asm volatile(
      "vpxord %%ymm1, %%ymm1, %%ymm1\n\t"
      "vmovups (%[a]), %%ymm0\n\t"
      "1:\n\t"
      "vaddps %%ymm0, %%ymm1, %%ymm2\n\t"
      "vaddps %%ymm0, %%ymm1, %%ymm3\n\t"
      "vaddps %%ymm0, %%ymm1, %%ymm4\n\t"
      "vaddps %%ymm0, %%ymm1, %%ymm5\n\t"
      "vaddps %%ymm0, %%ymm1, %%ymm6\n\t"
      "vaddps %%ymm0, %%ymm1, %%ymm7\n\t"
      "vaddps %%ymm0, %%ymm1, %%ymm8\n\t"
      "vaddps %%ymm0, %%ymm1, %%ymm9\n\t"
      "decl %[blocks]\n\t"
      "jne 1b\n\t"
      "movq (%[b]), %%r8\n\t"
      : [blocks] "+r"(blocks)
      : [a] "r"(g_line_a.data()), [b] "r"(g_line_b.data())
      : "cc", "memory", "r8", "zmm0", "zmm1", "zmm2", "zmm3",
        "zmm4", "zmm5", "zmm6", "zmm7", "zmm8", "zmm9");
  return ReadTscEnd() - start;
}

std::uint64_t MeasureLoadQueue(int blocks) {
  g_line_a[0] = reinterpret_cast<std::uintptr_t>(g_target.data());
  benchmark::DoNotOptimize(g_target[0]);
  FlushProbeLines();
  const std::uint64_t start = ReadTscStart();
  asm volatile(
      "movq (%[a]), %%rax\n\t"
      "1:\n\t"
      ".rept 8\n\t"
      "movq (%%rax), %%r10\n\t"
      ".endr\n\t"
      "decl %[blocks]\n\t"
      "jne 1b\n\t"
      "movq (%[b]), %%r8\n\t"
      : [blocks] "+r"(blocks)
      : [a] "r"(g_line_a.data()), [b] "r"(g_line_b.data())
      : "cc", "memory", "rax", "r8", "r10");
  return ReadTscEnd() - start;
}

std::uint64_t MeasureStoreQueue(int blocks) {
  g_line_a[0] = reinterpret_cast<std::uintptr_t>(g_target.data());
  benchmark::DoNotOptimize(g_target[0]);
  FlushProbeLines();
  const std::uint64_t value = 0x1234;
  const std::uint64_t start = ReadTscStart();
  asm volatile(
      "movq (%[a]), %%rax\n\t"
      "1:\n\t"
      ".rept 8\n\t"
      "movq %[value], (%%rax)\n\t"
      ".endr\n\t"
      "decl %[blocks]\n\t"
      "jne 1b\n\t"
      "movq (%[b]), %%r8\n\t"
      : [blocks] "+r"(blocks)
      : [a] "r"(g_line_a.data()), [b] "r"(g_line_b.data()),
        [value] "r"(value)
      : "cc", "memory", "rax", "r8");
  return ReadTscEnd() - start;
}

using MeasureFunction = std::uint64_t (*)(int);

void BM_WindowCapacity(benchmark::State& state, MeasureFunction measure,
                       std::uint16_t stall_event, std::uint8_t stall_mask,
                       int entries_per_block) {
  const int blocks = static_cast<int>(state.range(0));
  constexpr int kTrials = 400;
  auto events = amd_profile::PerfEventGroup::Open({
      amd_profile::CoreCycles(),
      amd_profile::RawEvent("resource_stall_cycles", stall_event, stall_mask),
      amd_profile::RawEvent("retired_macro_ops", 0xc1, 0x00),
  });
  std::string error;
  if (!amd_profile::StartEvents(state, &events, &error)) {
    return;
  }
  std::uint64_t total_tsc = 0;
  for (auto _ : state) {
    benchmark::DoNotOptimize(_);
    for (int trial = 0; trial < kTrials; ++trial) {
      total_tsc += measure(blocks);
    }
  }
  std::vector<amd_profile::EventValue> values;
  if (!amd_profile::StopEvents(state, &events, &values, &error)) {
    return;
  }
  const double trials = static_cast<double>(state.iterations()) * kTrials;
  state.counters["blocked_entries"] = blocks * entries_per_block;
  state.counters["probe_tsc_cycles"] =
      static_cast<double>(total_tsc) / trials;
  state.counters["stall_cycles_per_trial"] =
      amd_profile::FindEvent(values, "resource_stall_cycles") / trials;
}

void RegisterWindowBenchmarks() {
  const std::array<int, 17> rob_blocks = {8,  10, 12, 14, 16, 17,
                                          18, 19, 20, 21, 22, 23,
                                          24, 26, 28, 30, 32};
  auto* rob = benchmark::RegisterBenchmark(
      "WindowCapacity/ROB", BM_WindowCapacity, MeasureRobWindow, 0xaf, 0x20,
      17);
  for (int value : rob_blocks) {
    rob->Arg(value);
  }
  rob->Iterations(1);

  const std::array<int, 15> queue_blocks = {2, 3, 4, 5, 6, 7, 8, 9,
                                            10, 11, 12, 13, 14, 16, 18};
  auto* scheduler = benchmark::RegisterBenchmark(
      "WindowCapacity/VectorScheduler", BM_WindowCapacity,
      MeasureVectorScheduler, 0xae, 0x40, 8);
  auto* load_queue = benchmark::RegisterBenchmark(
      "WindowCapacity/LoadQueue", BM_WindowCapacity, MeasureLoadQueue, 0xae,
      0x02, 8);
  auto* store_queue = benchmark::RegisterBenchmark(
      "WindowCapacity/StoreQueue", BM_WindowCapacity, MeasureStoreQueue, 0xae,
      0x04, 8);
  for (int value : queue_blocks) {
    scheduler->Arg(value);
    load_queue->Arg(value);
    store_queue->Arg(value);
  }
  scheduler->Iterations(1);
  load_queue->Iterations(1);
  store_queue->Iterations(1);
}

const bool kRegistered = [] {
  RegisterWindowBenchmarks();
  return true;
}();

}  // namespace
