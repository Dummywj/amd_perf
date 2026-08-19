#include <am.h>
#include <klib.h>

#include <stddef.h>
#include <stdint.h>

#include "perf_counters.h"

#ifndef XSAI_VSET_GAP_SAMPLES
#define XSAI_VSET_GAP_SAMPLES 5
#endif

#ifndef XSAI_VSET_GAP_ITERATIONS
#define XSAI_VSET_GAP_ITERATIONS 64
#endif

extern "C" {
void xsai_vg_regular_lfs(const float*, float*, size_t);
void xsai_vg_keep_vl_lfs(const float*, float*, size_t);
void xsai_vg_vlmax_lfs(const float*, float*, size_t);
void xsai_vg_outside_lfs(const float*, float*, size_t);
void xsai_vg_regular_load(const float*, float*, size_t);
void xsai_vg_regular_compute(const float*, float*, size_t);
void xsai_vg_regular_store(const float*, float*, size_t);
}

namespace {

using BenchFunction = void (*)(const float*, float*, size_t);

constexpr size_t kArenaElements = 2048;
constexpr size_t kL1DBytes = 64 * 1024;
constexpr size_t kElementsPerIteration = 4;

enum class ResultKind { kLoadFmaStore, kLoadOnly, kComputeOnly, kStoreOnly };

struct BenchSpec {
  const char* name;
  const char* form;
  const char* consumer;
  BenchFunction function;
  ResultKind result_kind;
};

const BenchSpec kBenches[] = {
    {"regular_lfs", "rd_rs1", "load_fma_store", xsai_vg_regular_lfs,
     ResultKind::kLoadFmaStore},
    {"keep_vl_lfs", "x0_x0", "load_fma_store", xsai_vg_keep_vl_lfs,
     ResultKind::kLoadFmaStore},
    {"vlmax_lfs", "rd_x0", "load_fma_store", xsai_vg_vlmax_lfs,
     ResultKind::kLoadFmaStore},
    {"outside_lfs", "outside", "load_fma_store", xsai_vg_outside_lfs,
     ResultKind::kLoadFmaStore},
    {"regular_load", "rd_rs1", "load_only", xsai_vg_regular_load,
     ResultKind::kLoadOnly},
    {"regular_compute", "rd_rs1", "compute_only", xsai_vg_regular_compute,
     ResultKind::kComputeOnly},
    {"regular_store", "rd_rs1", "store_only", xsai_vg_regular_store,
     ResultKind::kStoreOnly},
};

union FloatBits {
  float value;
  uint32_t bits;
};

inline uint64_t ReadCycle() {
  uint64_t value;
  asm volatile("csrr %0, mcycle" : "=r"(value) : : "memory");
  return value;
}

inline void MeasurementFence() { asm volatile("fence rw, rw" : : : "memory"); }

void EnableVectorState() {
  const uintptr_t vector_state = 0x600;
  asm volatile("csrs mstatus, %0\n\tcsrwi vcsr, 0"
               :
               : "r"(vector_state)
               : "memory");
}

__attribute__((noinline)) void EmptyBench(const float*, float*, size_t) {
  asm volatile("" : : : "memory");
}

uint64_t Measure(BenchFunction function, const float* input, float* output,
                 size_t iterations) {
  MeasurementFence();
  const uint64_t begin = ReadCycle();
  function(input, output, iterations);
  MeasurementFence();
  return ReadCycle() - begin;
}

inline float Abs(float value) { return value < 0.0f ? -value : value; }

}  // namespace

extern "C" {
alignas(64) float xsai_vset_gap_input[kArenaElements];
alignas(64) float xsai_vset_gap_output[kArenaElements];
}

namespace {

void ResetArenas() {
  for (size_t index = 0; index < kArenaElements; ++index) {
    xsai_vset_gap_input[index] =
        0.25f + static_cast<float>(index % 31) * 0.01f;
    xsai_vset_gap_output[index] = -1234.0f;
  }
}

bool NearlyEqual(float actual, float expected) {
  return Abs(actual - expected) <= 1.0e-5f;
}

bool CheckResult(const BenchSpec& spec, size_t iterations) {
  switch (spec.result_kind) {
    case ResultKind::kLoadFmaStore:
      for (size_t index = 0; index < iterations * kElementsPerIteration;
           ++index) {
        const size_t lane = index % kElementsPerIteration;
        const float expected = __builtin_fmaf(
            xsai_vset_gap_input[lane], xsai_vset_gap_input[4 + lane],
            xsai_vset_gap_input[8 + index]);
        if (!NearlyEqual(xsai_vset_gap_output[index], expected)) return false;
      }
      return true;
    case ResultKind::kLoadOnly:
      for (size_t lane = 0; lane < kElementsPerIteration; ++lane) {
        const size_t index =
            8 + (iterations - 1) * kElementsPerIteration + lane;
        if (!NearlyEqual(xsai_vset_gap_output[lane],
                         xsai_vset_gap_input[index]))
          return false;
      }
      return true;
    case ResultKind::kComputeOnly:
      for (size_t lane = 0; lane < kElementsPerIteration; ++lane) {
        float expected = xsai_vset_gap_input[8 + lane];
        for (size_t iteration = 0; iteration < iterations; ++iteration)
          expected = __builtin_fmaf(xsai_vset_gap_input[lane],
                                    xsai_vset_gap_input[4 + lane], expected);
        if (!NearlyEqual(xsai_vset_gap_output[lane], expected)) return false;
      }
      return true;
    case ResultKind::kStoreOnly:
      for (size_t index = 0; index < iterations * kElementsPerIteration;
           ++index) {
        if (!NearlyEqual(xsai_vset_gap_output[index],
                         xsai_vset_gap_input[index % kElementsPerIteration]))
          return false;
      }
      return true;
  }
  return false;
}

uint64_t OutputChecksum(size_t count) {
  uint64_t hash = 1469598103934665603ULL;
  for (size_t index = 0; index < count; ++index) {
    FloatBits converted;
    converted.value = xsai_vset_gap_output[index];
    hash ^= converted.bits;
    hash *= 1099511628211ULL;
  }
  return hash;
}

bool RunBench(const BenchSpec& spec) {
  using softmax_sim::xsai::BeginTimedRegionHpm;
  using softmax_sim::xsai::CutePathInactive;
  using softmax_sim::xsai::EndTimedRegionHpm;
  using softmax_sim::xsai::HpmSnapshot;
  using softmax_sim::xsai::PrintHpmAudit;
  using softmax_sim::xsai::SubtractHpmSnapshots;

  constexpr size_t iterations = XSAI_VSET_GAP_ITERATIONS;
  constexpr size_t warmup_iterations = 8;
  ResetArenas();
  spec.function(xsai_vset_gap_input, xsai_vset_gap_output, warmup_iterations);

  bool passed = true;
  for (int sample = 0; sample < XSAI_VSET_GAP_SAMPLES; ++sample) {
    const uint64_t empty_cycles =
        Measure(EmptyBench, xsai_vset_gap_input, xsai_vset_gap_output,
                iterations);
    const HpmSnapshot hpm_begin = BeginTimedRegionHpm();
    const uint64_t raw_cycles =
        Measure(spec.function, xsai_vset_gap_input, xsai_vset_gap_output,
                iterations);
    const HpmSnapshot hpm_delta =
        SubtractHpmSnapshots(EndTimedRegionHpm(), hpm_begin);
    const uint64_t cycles =
        raw_cycles > empty_cycles ? raw_cycles - empty_cycles : 0;
    const bool sample_passed = CheckResult(spec, iterations) &&
                               CutePathInactive(hpm_delta);
    passed &= sample_passed;
    const size_t output_count =
        spec.result_kind == ResultKind::kLoadOnly ||
                spec.result_kind == ResultKind::kComputeOnly
            ? kElementsPerIteration
            : iterations * kElementsPerIteration;
    printf(
        "XSAI_VSET_RESULT name=%s form=%s consumer=%s sample=%d "
        "iterations=%lu raw_cycles=%lu empty_cycles=%lu cycles=%lu "
        "checksum=0x%lx status=%s\n",
        spec.name, spec.form, spec.consumer, sample,
        static_cast<unsigned long>(iterations),
        static_cast<unsigned long>(raw_cycles),
        static_cast<unsigned long>(empty_cycles),
        static_cast<unsigned long>(cycles),
        static_cast<unsigned long>(OutputChecksum(output_count)),
        sample_passed ? "PASS" : "FAIL");
    PrintHpmAudit(spec.name, iterations, sample, hpm_delta);
  }
  return passed;
}

}  // namespace

int main(const char*) {
  EnableVectorState();
  softmax_sim::xsai::InitializeHpmCounters();
  printf(
      "XSAI_VSET_META format=1 isa=rv64gcv_zvl128b vlen_bits=128 "
      "samples=%d cases=%lu iterations=%d elements_per_iteration=%lu "
      "l1d_bytes=%lu cute_instructions=0 hpm_audit=1\n",
      XSAI_VSET_GAP_SAMPLES,
      static_cast<unsigned long>(sizeof(kBenches) / sizeof(kBenches[0])),
      XSAI_VSET_GAP_ITERATIONS,
      static_cast<unsigned long>(kElementsPerIteration),
      static_cast<unsigned long>(kL1DBytes));
  printf(
      "XSAI_VSET_LAYOUT input=0x%lx input_bytes=%lu output=0x%lx "
      "output_bytes=%lu line_bytes=64 sets=256 ways=4\n",
      reinterpret_cast<unsigned long>(xsai_vset_gap_input),
      static_cast<unsigned long>(sizeof(xsai_vset_gap_input)),
      reinterpret_cast<unsigned long>(xsai_vset_gap_output),
      static_cast<unsigned long>(sizeof(xsai_vset_gap_output)));

  bool passed = true;
  for (const BenchSpec& bench : kBenches) passed &= RunBench(bench);
  printf("XSAI_VSET_DONE status=%s cases=%lu samples=%lu\n",
         passed ? "PASS" : "FAIL",
         static_cast<unsigned long>(sizeof(kBenches) / sizeof(kBenches[0])),
         static_cast<unsigned long>((sizeof(kBenches) / sizeof(kBenches[0])) *
                                    XSAI_VSET_GAP_SAMPLES));
  return passed ? 0 : 1;
}
