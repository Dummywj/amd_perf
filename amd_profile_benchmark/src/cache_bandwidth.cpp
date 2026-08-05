#include <benchmark/benchmark.h>
#include <immintrin.h>
#include <sys/mman.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#include "benchmark_common.h"

namespace {

constexpr std::size_t kBytesPerBlock = 8 * 64;
constexpr std::size_t kYmmBytesPerBlock = 8 * 32;

__attribute__((noinline)) void ReadBlocks(const std::byte* data,
                                          std::size_t bytes, int passes) {
  for (int pass = 0; pass < passes; ++pass) {
    for (std::size_t offset = 0; offset < bytes; offset += kBytesPerBlock) {
      const std::byte* pointer = data + offset;
      asm volatile(
          "vmovups 0(%[p]), %%zmm0\n\t"
          "vmovups 64(%[p]), %%zmm1\n\t"
          "vmovups 128(%[p]), %%zmm2\n\t"
          "vmovups 192(%[p]), %%zmm3\n\t"
          "vmovups 256(%[p]), %%zmm4\n\t"
          "vmovups 320(%[p]), %%zmm5\n\t"
          "vmovups 384(%[p]), %%zmm6\n\t"
          "vmovups 448(%[p]), %%zmm7\n\t"
          :
          : [p] "r"(pointer)
          : "memory", "zmm0", "zmm1", "zmm2", "zmm3", "zmm4", "zmm5",
            "zmm6", "zmm7");
    }
  }
}

__attribute__((noinline)) void WriteBlocks(std::byte* data, std::size_t bytes,
                                           int passes) {
  asm volatile("vpxord %%zmm0, %%zmm0, %%zmm0" ::: "zmm0");
  for (int pass = 0; pass < passes; ++pass) {
    for (std::size_t offset = 0; offset < bytes; offset += kBytesPerBlock) {
      std::byte* pointer = data + offset;
      asm volatile(
          "vmovups %%zmm0, 0(%[p])\n\t"
          "vmovups %%zmm0, 64(%[p])\n\t"
          "vmovups %%zmm0, 128(%[p])\n\t"
          "vmovups %%zmm0, 192(%[p])\n\t"
          "vmovups %%zmm0, 256(%[p])\n\t"
          "vmovups %%zmm0, 320(%[p])\n\t"
          "vmovups %%zmm0, 384(%[p])\n\t"
          "vmovups %%zmm0, 448(%[p])\n\t"
          :
          : [p] "r"(pointer)
          : "memory");
    }
  }
}

using BandwidthKernel = void (*)(std::byte*, std::size_t, int);

void ReadAdapter(std::byte* data, std::size_t bytes, int passes) {
  ReadBlocks(data, bytes, passes);
}

__attribute__((noinline)) void ReadBlocksYmm(const std::byte* data,
                                             std::size_t bytes, int passes) {
  for (int pass = 0; pass < passes; ++pass) {
    for (std::size_t offset = 0; offset < bytes;
         offset += kYmmBytesPerBlock) {
      const std::byte* pointer = data + offset;
      asm volatile(
          "vmovups 0(%[p]), %%ymm0\n\t"
          "vmovups 32(%[p]), %%ymm1\n\t"
          "vmovups 64(%[p]), %%ymm2\n\t"
          "vmovups 96(%[p]), %%ymm3\n\t"
          "vmovups 128(%[p]), %%ymm4\n\t"
          "vmovups 160(%[p]), %%ymm5\n\t"
          "vmovups 192(%[p]), %%ymm6\n\t"
          "vmovups 224(%[p]), %%ymm7\n\t"
          :
          : [p] "r"(pointer)
          : "memory", "zmm0", "zmm1", "zmm2", "zmm3", "zmm4", "zmm5",
            "zmm6", "zmm7");
    }
  }
}

__attribute__((noinline)) void WriteBlocksYmm(std::byte* data,
                                              std::size_t bytes, int passes) {
  asm volatile("vpxord %%zmm0, %%zmm0, %%zmm0" ::: "zmm0");
  for (int pass = 0; pass < passes; ++pass) {
    for (std::size_t offset = 0; offset < bytes;
         offset += kYmmBytesPerBlock) {
      std::byte* pointer = data + offset;
      asm volatile(
          "vmovups %%ymm0, 0(%[p])\n\t"
          "vmovups %%ymm0, 32(%[p])\n\t"
          "vmovups %%ymm0, 64(%[p])\n\t"
          "vmovups %%ymm0, 96(%[p])\n\t"
          "vmovups %%ymm0, 128(%[p])\n\t"
          "vmovups %%ymm0, 160(%[p])\n\t"
          "vmovups %%ymm0, 192(%[p])\n\t"
          "vmovups %%ymm0, 224(%[p])\n\t"
          :
          : [p] "r"(pointer)
          : "memory");
    }
  }
}

void ReadYmmAdapter(std::byte* data, std::size_t bytes, int passes) {
  ReadBlocksYmm(data, bytes, passes);
}

void BM_L1MixedYmm(benchmark::State& state) {
  constexpr std::size_t bytes = 16 << 10;
  constexpr int passes = 131072;
  constexpr std::size_t logical_bytes_per_block = 12 * 32;
  amd_profile::AlignedBuffer<std::byte> data(bytes);
  std::memset(data.data(), 1, bytes);
  asm volatile("vpxord %%zmm8, %%zmm8, %%zmm8" ::: "zmm8");

  auto events =
      amd_profile::PerfEventGroup::Open({amd_profile::CoreCycles()});
  std::string error;
  if (!amd_profile::StartEvents(state, &events, &error)) {
    return;
  }
  for (auto _ : state) {
    benchmark::DoNotOptimize(_);
    for (int pass = 0; pass < passes; ++pass) {
      for (std::size_t offset = 0; offset < bytes;
           offset += kBytesPerBlock) {
        std::byte* pointer = data.data() + offset;
        asm volatile(
            "vmovups 0(%[p]), %%ymm0\n\t"
            "vmovups 32(%[p]), %%ymm1\n\t"
            "vmovups %%ymm8, 64(%[p])\n\t"
            "vmovups 96(%[p]), %%ymm2\n\t"
            "vmovups 128(%[p]), %%ymm3\n\t"
            "vmovups %%ymm8, 160(%[p])\n\t"
            "vmovups 192(%[p]), %%ymm4\n\t"
            "vmovups 224(%[p]), %%ymm5\n\t"
            "vmovups %%ymm8, 256(%[p])\n\t"
            "vmovups 288(%[p]), %%ymm6\n\t"
            "vmovups 320(%[p]), %%ymm7\n\t"
            "vmovups %%ymm8, 352(%[p])\n\t"
            :
            : [p] "r"(pointer)
            : "memory", "zmm0", "zmm1", "zmm2", "zmm3", "zmm4", "zmm5",
              "zmm6", "zmm7", "zmm8");
      }
    }
  }
  std::vector<amd_profile::EventValue> values;
  if (!amd_profile::StopEvents(state, &events, &values, &error)) {
    return;
  }
  const double blocks = static_cast<double>(state.iterations()) * passes *
                        (bytes / kBytesPerBlock);
  const double operations = blocks * 12;
  const double logical_bytes = blocks * logical_bytes_per_block;
  const double cycles = amd_profile::FindEvent(values, "core_cycles");
  state.counters["memory_ops_per_cycle"] = operations / cycles;
  state.counters["bytes_per_cycle"] = logical_bytes / cycles;
}

void BM_CacheBandwidth(benchmark::State& state, BandwidthKernel kernel,
                       bool is_store) {
  const std::size_t bytes = static_cast<std::size_t>(state.range(0));
  const int passes = static_cast<int>(state.range(1));
  amd_profile::AlignedBuffer<std::byte> data(bytes);
  std::memset(data.data(), 1, bytes);
  (void)madvise(data.data(), bytes, MADV_HUGEPAGE);
  ReadBlocks(data.data(), bytes, 1);

  const std::uint8_t dispatch_mask = is_store ? 0x02 : 0x01;
  auto events = amd_profile::PerfEventGroup::Open({
      amd_profile::CoreCycles(),
      amd_profile::RawEvent("ls_dispatch_ops", 0x29, dispatch_mask),
      amd_profile::RawEvent("l2_demand_misses", 0x64, 0x08),
  });
  std::string error;
  if (!amd_profile::StartEvents(state, &events, &error)) {
    return;
  }
  for (auto _ : state) {
    benchmark::DoNotOptimize(_);
    kernel(data.data(), bytes, passes);
  }
  std::vector<amd_profile::EventValue> values;
  if (!amd_profile::StopEvents(state, &events, &values, &error)) {
    return;
  }

  const double logical_bytes = static_cast<double>(state.iterations()) *
                               bytes * passes;
  const double cycles = amd_profile::FindEvent(values, "core_cycles");
  state.SetBytesProcessed(static_cast<std::int64_t>(logical_bytes));
  state.counters["working_set_bytes"] = static_cast<double>(bytes);
  state.counters["passes"] = passes;
  state.counters["bytes_per_cycle"] = logical_bytes / cycles;
  state.counters["vector_memory_ops_per_cycle"] =
      amd_profile::FindEvent(values, "ls_dispatch_ops") / cycles;
  state.counters["l2_misses_per_kib"] =
      amd_profile::FindEvent(values, "l2_demand_misses") /
      (logical_bytes / 1024.0);
}

void RegisterBandwidth(const char* level, std::int64_t bytes,
                       std::int64_t passes) {
  const std::string read_name = std::string("CacheBandwidth/Read/") + level;
  benchmark::RegisterBenchmark(read_name.c_str(), BM_CacheBandwidth,
                               ReadAdapter, false)
      ->Args({bytes, passes})
      ->Iterations(1);
  const std::string write_name = std::string("CacheBandwidth/Write/") + level;
  benchmark::RegisterBenchmark(write_name.c_str(), BM_CacheBandwidth,
                               WriteBlocks, true)
      ->Args({bytes, passes})
      ->Iterations(1);
}

const bool kRegistered = [] {
  RegisterBandwidth("L1D", 16LL << 10, 131072);
  RegisterBandwidth("L2", 256LL << 10, 8192);
  RegisterBandwidth("L3", 16LL << 20, 128);
  RegisterBandwidth("DRAM", 256LL << 20, 4);
  benchmark::RegisterBenchmark("CacheBandwidth/ReadYmm/L1D",
                               BM_CacheBandwidth, ReadYmmAdapter, false)
      ->Args({16LL << 10, 131072})
      ->Iterations(1);
  benchmark::RegisterBenchmark("CacheBandwidth/WriteYmm/L1D",
                               BM_CacheBandwidth, WriteBlocksYmm, true)
      ->Args({16LL << 10, 131072})
      ->Iterations(1);
  benchmark::RegisterBenchmark("CacheBandwidth/MixedYmm/L1D", BM_L1MixedYmm)
      ->Iterations(1);
  return true;
}();

}  // namespace
