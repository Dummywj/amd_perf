#include <am.h>
#include <klib.h>

#include <stddef.h>
#include <stdint.h>

#include "common/kernel_interface.h"
#include "common/softmax_constants.h"
#include "common/softmax_interface.h"
#include "perf_counters.h"

#ifndef XSAI_BENCH_SAMPLES
#define XSAI_BENCH_SAMPLES 5
#endif

#ifndef XSAI_PROFILE_ITERATIONS
#define XSAI_PROFILE_ITERATIONS 64
#endif

extern "C" {
void xsai_mb_loop_baseline(const float*, float*, size_t);
void xsai_mb_scalar_alu_dependency(const float*, float*, size_t);
void xsai_mb_scalar_alu_throughput(const float*, float*, size_t);
void xsai_mb_scalar_fp_add_dependency(const float*, float*, size_t);
void xsai_mb_scalar_fp_add_throughput(const float*, float*, size_t);
void xsai_mb_scalar_fp_div_dependency(const float*, float*, size_t);
void xsai_mb_vset_throughput(const float*, float*, size_t);
void xsai_mb_fma_dependency(const float*, float*, size_t);
void xsai_mb_fma_throughput(const float*, float*, size_t);
void xsai_mb_fp_add_dependency(const float*, float*, size_t);
void xsai_mb_fp_add_throughput(const float*, float*, size_t);
void xsai_mb_fp_add_same_vd(const float*, float*, size_t);
void xsai_mb_integer_dependency(const float*, float*, size_t);
void xsai_mb_integer_throughput(const float*, float*, size_t);
void xsai_mb_integer_same_vd(const float*, float*, size_t);
void xsai_mb_conversion_dependency(const float*, float*, size_t);
void xsai_mb_conversion_throughput(const float*, float*, size_t);
void xsai_mb_conversion_same_vd(const float*, float*, size_t);
void xsai_mb_conversion_integer(const float*, float*, size_t);
void xsai_mb_fma_integer(const float*, float*, size_t);
void xsai_mb_conversion_fma_integer(const float*, float*, size_t);
void xsai_mb_reduction_sum_dependency(const float*, float*, size_t);
void xsai_mb_reduction_sum_throughput(const float*, float*, size_t);
void xsai_mb_reduction_max_dependency(const float*, float*, size_t);
void xsai_mb_reduction_max_throughput(const float*, float*, size_t);
void xsai_mb_fma_scalar_dependency(const float*, float*, size_t);
void xsai_mb_fma_scalar_throughput(const float*, float*, size_t);
void xsai_mb_fp_broadcast_throughput(const float*, float*, size_t);
void xsai_mb_integer_scalar_throughput(const float*, float*, size_t);
void xsai_mb_immediate_broadcast_throughput(const float*, float*, size_t);
void xsai_mb_load_throughput(const float*, float*, size_t);
void xsai_mb_load_stream_throughput(const float*, float*, size_t);
void xsai_mb_load_same_vd(const float*, float*, size_t);
void xsai_mb_load_use(const float*, float*, size_t);
void xsai_mb_load_alu_dependency(const float*, float*, size_t);
void xsai_mb_load_fma_dependency(const float*, float*, size_t);
void xsai_mb_store_throughput(const float*, float*, size_t);
void xsai_mb_store_stream_throughput(const float*, float*, size_t);
void xsai_mb_load_fma_iteration(const float*, float*, size_t);
void xsai_mb_load_fma_store_iteration(const float*, float*, size_t);
void xsai_mb_vset_rd_dependency(const float*, float*, size_t);
}

namespace {

constexpr size_t kMaxCount = 2048;
constexpr size_t kMaxInputVectors = 3;
constexpr size_t kL1DBytes = 64 * 1024;

enum class KernelKind {
  kFmaThroughput,
  kFmaLatency,
  kAxpy,
  kVectorCopy,
  kVectorTriad,
  kPointerAgu,
  kDotProduct,
  kVectorReduction,
  kConversion,
  kVectorInteger,
  kMixedCompute,
  kSoftmax,
};

struct KernelSpec {
  const char* name;
  KernelF32 function;
  size_t input_vectors;
  size_t output_count;
  float tolerance;
  KernelKind kind;
};

struct MicrobenchSpec {
  const char* name;
  KernelF32 function;
  const char* category;
  size_t operations_per_iteration;
  const char* unit;
};

const KernelSpec kKernels[] = {
    {"fma_throughput", fma_throughput_rvv_f32, 1, 0, 3.0e-5f,
     KernelKind::kFmaThroughput},
    {"fma_latency", fma_latency_rvv_f32, 1, 0, 3.0e-5f,
     KernelKind::kFmaLatency},
    {"axpy", axpy_rvv_f32, 2, 0, 3.0e-6f, KernelKind::kAxpy},
    {"vector_copy", vector_copy_rvv_f32, 1, 0, 0.0f,
     KernelKind::kVectorCopy},
    {"vector_triad", vector_triad_rvv_f32, 2, 0, 3.0e-6f,
     KernelKind::kVectorTriad},
    {"pointer_agu", pointer_agu_rvv_f32, 3, 0, 3.0e-6f,
     KernelKind::kPointerAgu},
    {"dot_product", dot_product_rvv_f32, 2, 1, 2.0e-2f,
     KernelKind::kDotProduct},
    {"vector_reduction", vector_reduction_rvv_f32, 1, 2, 2.0e-2f,
     KernelKind::kVectorReduction},
    {"conversion", conversion_rvv_f32, 1, 0, 0.0f,
     KernelKind::kConversion},
    {"vector_integer", vector_integer_rvv_f32, 1, 0, 0.0f,
     KernelKind::kVectorInteger},
    {"mixed_compute", mixed_compute_rvv_f32, 1, 0, 3.0e-6f,
     KernelKind::kMixedCompute},
    {"softmax", softmax_rvv_f32, 1, 0, 1.0e-4f, KernelKind::kSoftmax},
};

const MicrobenchSpec kMicrobenches[] = {
    {"loop16_baseline", xsai_mb_loop_baseline, "baseline", 16, "nop"},
    {"scalar_alu_dependency", xsai_mb_scalar_alu_dependency, "dependency", 16,
     "instruction"},
    {"scalar_alu_throughput", xsai_mb_scalar_alu_throughput, "throughput", 16,
     "instruction"},
    {"scalar_fp_add_dependency", xsai_mb_scalar_fp_add_dependency, "dependency",
     16, "instruction"},
    {"scalar_fp_add_throughput", xsai_mb_scalar_fp_add_throughput, "throughput",
     16, "instruction"},
    {"scalar_fp_div_dependency", xsai_mb_scalar_fp_div_dependency, "dependency",
     8, "instruction"},
    {"vset_throughput", xsai_mb_vset_throughput, "throughput", 16,
     "instruction"},
    {"fma_dependency", xsai_mb_fma_dependency, "dependency", 16,
     "instruction"},
    {"fma_throughput", xsai_mb_fma_throughput, "throughput", 16,
     "instruction"},
    {"fp_add_dependency", xsai_mb_fp_add_dependency, "dependency", 16,
     "instruction"},
    {"fp_add_throughput", xsai_mb_fp_add_throughput, "throughput", 16,
     "instruction"},
    {"fp_add_same_vd", xsai_mb_fp_add_same_vd, "same_vd", 16,
     "instruction"},
    {"integer_dependency", xsai_mb_integer_dependency, "dependency", 16,
     "instruction"},
    {"integer_throughput", xsai_mb_integer_throughput, "throughput", 16,
     "instruction"},
    {"integer_same_vd", xsai_mb_integer_same_vd, "same_vd", 16,
     "instruction"},
    {"conversion_dependency", xsai_mb_conversion_dependency, "dependency", 16,
     "instruction"},
    {"conversion_throughput", xsai_mb_conversion_throughput, "throughput", 16,
     "instruction"},
    {"conversion_same_vd", xsai_mb_conversion_same_vd, "same_vd", 16,
     "instruction"},
    {"conversion_integer", xsai_mb_conversion_integer, "contention", 16,
     "instruction"},
    {"fma_integer", xsai_mb_fma_integer, "contention", 16, "instruction"},
    {"conversion_fma_integer", xsai_mb_conversion_fma_integer, "contention",
     16, "instruction"},
    {"reduction_sum_dependency", xsai_mb_reduction_sum_dependency,
     "dependency", 16, "instruction"},
    {"reduction_sum_throughput", xsai_mb_reduction_sum_throughput,
     "throughput", 16, "instruction"},
    {"reduction_max_dependency", xsai_mb_reduction_max_dependency,
     "dependency", 16, "instruction"},
    {"reduction_max_throughput", xsai_mb_reduction_max_throughput,
     "throughput", 16, "instruction"},
    {"fma_scalar_dependency", xsai_mb_fma_scalar_dependency, "dependency", 16,
     "instruction"},
    {"fma_scalar_throughput", xsai_mb_fma_scalar_throughput, "throughput", 16,
     "instruction"},
    {"fp_broadcast_throughput", xsai_mb_fp_broadcast_throughput, "throughput",
     16, "instruction"},
    {"integer_scalar_throughput", xsai_mb_integer_scalar_throughput,
     "throughput", 16, "instruction"},
    {"immediate_broadcast_throughput", xsai_mb_immediate_broadcast_throughput,
     "throughput", 16, "instruction"},
    {"load_throughput", xsai_mb_load_throughput, "memory", 16, "load"},
    {"load_stream_throughput", xsai_mb_load_stream_throughput,
     "memory_stream", 16, "load"},
    {"load_same_vd", xsai_mb_load_same_vd, "memory_dependency", 16, "load"},
    {"load_use", xsai_mb_load_use, "memory", 8, "load_use_pair"},
    {"load_alu_dependency", xsai_mb_load_alu_dependency, "memory_dependency",
     8, "load_alu_pair"},
    {"load_fma_dependency", xsai_mb_load_fma_dependency, "memory_dependency",
     8, "load_fma_pair"},
    {"store_throughput", xsai_mb_store_throughput, "memory", 16, "store"},
    {"store_stream_throughput", xsai_mb_store_stream_throughput,
     "memory_stream", 16, "store"},
    {"load_fma_iteration", xsai_mb_load_fma_iteration, "iteration", 1,
     "iteration"},
    {"load_fma_store_iteration", xsai_mb_load_fma_store_iteration,
     "iteration", 1, "iteration"},
    {"vset_rd_dependency", xsai_mb_vset_rd_dependency, "dependency", 16,
     "instruction"},
};

union FloatBits {
  float value;
  uint32_t bits;
};

inline float Abs(float value) { return value < 0.0f ? -value : value; }

inline bool IsFinite(float value) {
  FloatBits converted = {.value = value};
  return (converted.bits & 0x7f800000U) != 0x7f800000U;
}

inline uint64_t ReadCycle() {
  uint64_t value;
  asm volatile("csrr %0, mcycle" : "=r"(value) : : "memory");
  return value;
}

inline void MeasurementFence() { asm volatile("fence rw, rw" : : : "memory"); }

void EnableVectorState() {
  uintptr_t vector_state = 0x600;
  asm volatile("csrs mstatus, %0\n\tcsrwi vcsr, 0"
               :
               : "r"(vector_state)
               : "memory");
}

__attribute__((noinline)) void EmptyKernel(const float*, float*, size_t) {
  asm volatile("" : : : "memory");
}

uint64_t Measure(KernelF32 function, const float* input, float* output,
                 size_t count) {
  MeasurementFence();
  const uint64_t begin = ReadCycle();
  function(input, output, count);
  MeasurementFence();
  const uint64_t end = ReadCycle();
  return end - begin;
}

void FillInput(size_t count, size_t vectors, bool bit_pattern);
bool CheckOutput(const KernelSpec& spec, size_t count, float* maximum_error);
uint64_t OutputChecksum(size_t output_count);

float ExpApproxScalar(float value) {
  using namespace softmax_sim::kernel::softmax;
  value = value < kExpInputMin ? kExpInputMin : value;
  value = value > 0.0f ? 0.0f : value;
  const int32_t exponent = static_cast<int32_t>(value * kLog2E);
  const float reduced = value - static_cast<float>(exponent) * kLn2;
  float polynomial = kExpC7;
  polynomial = __builtin_fmaf(polynomial, reduced, kExpC6);
  polynomial = __builtin_fmaf(polynomial, reduced, kExpC5);
  polynomial = __builtin_fmaf(polynomial, reduced, kExpC4);
  polynomial = __builtin_fmaf(polynomial, reduced, kExpC3);
  polynomial = __builtin_fmaf(polynomial, reduced, kExpC2);
  polynomial = __builtin_fmaf(polynomial, reduced, kExpC1);
  polynomial = __builtin_fmaf(polynomial, reduced, kExpC0);
  FloatBits scale = {
      .bits = static_cast<uint32_t>(exponent + 127) << 23,
  };
  return polynomial * scale.value;
}

}  // namespace

extern "C" {
alignas(64) float xsai_input_arena[kMaxCount * kMaxInputVectors];
alignas(64) float xsai_output_arena[kMaxCount];
}

namespace {

void FillInput(size_t count, size_t vectors, bool bit_pattern) {
  uint32_t state = 0x12345678U;
  for (size_t index = 0; index < count * vectors; ++index) {
    state = state * 1664525U + 1013904223U;
    if (bit_pattern) {
      FloatBits value = {.bits = state & 0x000fffffU};
      xsai_input_arena[index] = value.value;
    } else {
      const int32_t signed_value =
          static_cast<int32_t>(state >> 8) - (1 << 23);
      xsai_input_arena[index] =
          static_cast<float>(signed_value) / static_cast<float>(1U << 20);
    }
  }
}

float ExpectedElement(const KernelSpec& spec, size_t index, size_t count) {
  const float x = xsai_input_arena[index];
  switch (spec.kind) {
    case KernelKind::kFmaThroughput: {
      float value = x;
      for (int round = 0; round < 16; ++round)
        value = __builtin_fmaf(value, 1.0001f, 0.0003f);
      return value;
    }
    case KernelKind::kAxpy:
      return __builtin_fmaf(1.25f, x, xsai_input_arena[count + index]);
    case KernelKind::kVectorCopy:
      return x;
    case KernelKind::kVectorTriad:
      return __builtin_fmaf(1.25f, xsai_input_arena[count + index], x);
    case KernelKind::kPointerAgu:
      return (x + xsai_input_arena[count + index]) +
             xsai_input_arena[2 * count + index];
    case KernelKind::kConversion:
      return static_cast<float>(static_cast<int32_t>(x));
    case KernelKind::kVectorInteger: {
      FloatBits converted = {.value = x};
      converted.bits = (converted.bits + 17U) << 1U;
      return converted.value;
    }
    case KernelKind::kMixedCompute: {
      const int32_t integer = (static_cast<int32_t>(x) + 17) << 1;
      return __builtin_fmaf(static_cast<float>(integer), 0.25f, x);
    }
    default:
      return 0.0f;
  }
}

bool Compare(float actual, float expected, float tolerance,
             float* maximum_error) {
  if (!IsFinite(actual) || !IsFinite(expected)) return false;
  const float error = Abs(actual - expected);
  if (error > *maximum_error) *maximum_error = error;
  if (tolerance == 0.0f) {
    FloatBits actual_bits = {.value = actual};
    FloatBits expected_bits = {.value = expected};
    return actual_bits.bits == expected_bits.bits;
  }
  return error <= tolerance;
}

bool CheckFmaLatency(size_t count, float tolerance, float* maximum_error) {
  float state[16] = {};
  bool passed = true;
  for (size_t base = 0; base < count; base += 16) {
    for (size_t lane = 0; lane < 16; ++lane) {
      state[lane] += xsai_input_arena[base + lane];
      for (int round = 0; round < 16; ++round)
        state[lane] = __builtin_fmaf(state[lane], 1.0001f, 0.0003f);
      passed &= Compare(xsai_output_arena[base + lane], state[lane], tolerance,
                        maximum_error);
    }
  }
  return passed;
}

bool CheckReduction(const KernelSpec& spec, size_t count,
                    float* maximum_error) {
  float sum = 0.0f;
  float maximum = -__builtin_inff();
  for (size_t index = 0; index < count; ++index) {
    sum += xsai_input_arena[index];
    if (xsai_input_arena[index] > maximum) maximum = xsai_input_arena[index];
  }
  if (spec.kind == KernelKind::kDotProduct) {
    sum = 0.0f;
    for (size_t index = 0; index < count; ++index)
      sum = __builtin_fmaf(xsai_input_arena[index],
                           xsai_input_arena[count + index], sum);
    return Compare(xsai_output_arena[0], sum, spec.tolerance, maximum_error);
  }
  return Compare(xsai_output_arena[0], sum, spec.tolerance, maximum_error) &&
         Compare(xsai_output_arena[1], maximum, spec.tolerance, maximum_error);
}

bool CheckSoftmax(size_t count, float tolerance, float* maximum_error) {
  float maximum = -__builtin_inff();
  for (size_t index = 0; index < count; ++index)
    if (xsai_input_arena[index] > maximum) maximum = xsai_input_arena[index];
  float sum = 0.0f;
  for (size_t index = 0; index < count; ++index)
    sum += ExpApproxScalar(xsai_input_arena[index] - maximum);
  const float inverse_sum = 1.0f / sum;
  bool passed = true;
  for (size_t index = 0; index < count; ++index) {
    const float expected =
        ExpApproxScalar(xsai_input_arena[index] - maximum) * inverse_sum;
    passed &= Compare(xsai_output_arena[index], expected, tolerance,
                      maximum_error);
  }
  return passed;
}

bool CheckOutput(const KernelSpec& spec, size_t count, float* maximum_error) {
  *maximum_error = 0.0f;
  if (spec.kind == KernelKind::kFmaLatency)
    return CheckFmaLatency(count, spec.tolerance, maximum_error);
  if (spec.kind == KernelKind::kDotProduct ||
      spec.kind == KernelKind::kVectorReduction)
    return CheckReduction(spec, count, maximum_error);
  if (spec.kind == KernelKind::kSoftmax)
    return CheckSoftmax(count, spec.tolerance, maximum_error);

  bool passed = true;
  for (size_t index = 0; index < count; ++index)
    passed &= Compare(xsai_output_arena[index],
                      ExpectedElement(spec, index, count), spec.tolerance,
                      maximum_error);
  return passed;
}

uint64_t OutputChecksum(size_t output_count) {
  uint64_t hash = 1469598103934665603ULL;
  for (size_t index = 0; index < output_count; ++index) {
    FloatBits converted = {.value = xsai_output_arena[index]};
    hash ^= converted.bits;
    hash *= 1099511628211ULL;
  }
  return hash;
}

bool RunCase(const KernelSpec& spec, size_t count) {
  using softmax_sim::xsai::BeginTimedRegionHpm;
  using softmax_sim::xsai::CutePathInactive;
  using softmax_sim::xsai::EndTimedRegionHpm;
  using softmax_sim::xsai::HpmSnapshot;
  using softmax_sim::xsai::PrintHpmAudit;
  using softmax_sim::xsai::SubtractHpmSnapshots;

  const size_t output_count = spec.output_count == 0 ? count : spec.output_count;
  FillInput(count, spec.input_vectors,
            spec.kind == KernelKind::kVectorInteger);
  for (size_t index = 0; index < output_count; ++index)
    xsai_output_arena[index] = 0.0f;

  spec.function(xsai_input_arena, xsai_output_arena, count);

  uint64_t raw_cycles[XSAI_BENCH_SAMPLES];
  uint64_t empty_cycles[XSAI_BENCH_SAMPLES];
  HpmSnapshot hpm_deltas[XSAI_BENCH_SAMPLES];
  bool audit_passed = true;
  for (int sample = 0; sample < XSAI_BENCH_SAMPLES; ++sample) {
    empty_cycles[sample] =
        Measure(EmptyKernel, xsai_input_arena, xsai_output_arena, count);
    const HpmSnapshot hpm_begin = BeginTimedRegionHpm();
    raw_cycles[sample] =
        Measure(spec.function, xsai_input_arena, xsai_output_arena, count);
    hpm_deltas[sample] =
        SubtractHpmSnapshots(EndTimedRegionHpm(), hpm_begin);
    audit_passed &= CutePathInactive(hpm_deltas[sample]);
  }

  float maximum_error = 0.0f;
  const bool passed = CheckOutput(spec, count, &maximum_error) && audit_passed;
  const uint64_t checksum = OutputChecksum(output_count);
  const uint64_t error_ppb = static_cast<uint64_t>(maximum_error * 1.0e9f);

  for (int sample = 0; sample < XSAI_BENCH_SAMPLES; ++sample) {
    const uint64_t corrected = raw_cycles[sample] > empty_cycles[sample]
                                   ? raw_cycles[sample] - empty_cycles[sample]
                                   : 0;
    printf("XSAI_RESULT kernel=%s n=%lu sample=%d raw_cycles=%lu "
           "empty_cycles=%lu cycles=%lu checksum=0x%lx max_error_ppb=%lu "
           "status=%s\n",
           spec.name, static_cast<unsigned long>(count), sample,
           static_cast<unsigned long>(raw_cycles[sample]),
           static_cast<unsigned long>(empty_cycles[sample]),
           static_cast<unsigned long>(corrected),
           static_cast<unsigned long>(checksum),
           static_cast<unsigned long>(error_ppb), passed ? "PASS" : "FAIL");
    PrintHpmAudit(spec.name, count, sample, hpm_deltas[sample]);
  }
  return passed;
}

void RunMicrobench(const MicrobenchSpec& spec) {
  using softmax_sim::xsai::BeginTimedRegionHpm;
  using softmax_sim::xsai::EndTimedRegionHpm;
  using softmax_sim::xsai::HpmSnapshot;
  using softmax_sim::xsai::PrintHpmAudit;
  using softmax_sim::xsai::SubtractHpmSnapshots;

  constexpr size_t iterations = XSAI_PROFILE_ITERATIONS;
  constexpr size_t warmup_iterations = 8;
  FillInput(64, 1, false);
  for (size_t index = 0; index < 64; ++index) xsai_output_arena[index] = 0.0f;
  spec.function(xsai_input_arena, xsai_output_arena, warmup_iterations);

  for (int sample = 0; sample < XSAI_BENCH_SAMPLES; ++sample) {
    const uint64_t empty_cycles =
        Measure(EmptyKernel, xsai_input_arena, xsai_output_arena, iterations);
    const HpmSnapshot hpm_begin = BeginTimedRegionHpm();
    const uint64_t raw_cycles =
        Measure(spec.function, xsai_input_arena, xsai_output_arena, iterations);
    const HpmSnapshot hpm_delta =
        SubtractHpmSnapshots(EndTimedRegionHpm(), hpm_begin);
    const uint64_t corrected =
        raw_cycles > empty_cycles ? raw_cycles - empty_cycles : 0;
    printf("XSAI_PARAM name=%s category=%s unit=%s sample=%d iterations=%lu "
           "operations=%lu raw_cycles=%lu empty_cycles=%lu cycles=%lu "
           "status=%s\n",
           spec.name, spec.category, spec.unit, sample,
           static_cast<unsigned long>(iterations),
           static_cast<unsigned long>(iterations * spec.operations_per_iteration),
           static_cast<unsigned long>(raw_cycles),
           static_cast<unsigned long>(empty_cycles),
           static_cast<unsigned long>(corrected),
           softmax_sim::xsai::CutePathInactive(hpm_delta) ? "PASS" : "FAIL");
    PrintHpmAudit(spec.name, iterations, sample, hpm_delta);
  }
}

}  // namespace

int main(const char*) {
  EnableVectorState();
  softmax_sim::xsai::InitializeHpmCounters();
  printf("XSAI_META format=2 isa=rv64gcv_zvl128b vlen_bits=128 samples=%d "
         "l1d_bytes=%lu cute_instructions=0 param_cases=%lu "
         "param_iterations=%d hpm_audit=1\n",
         XSAI_BENCH_SAMPLES, static_cast<unsigned long>(kL1DBytes),
         static_cast<unsigned long>(sizeof(kMicrobenches) / sizeof(kMicrobenches[0])),
         XSAI_PROFILE_ITERATIONS);
  printf("XSAI_LAYOUT input=0x%lx input_bytes=%lu output=0x%lx "
         "output_bytes=%lu line_bytes=64 sets=256 ways=4\n",
         reinterpret_cast<unsigned long>(xsai_input_arena),
         static_cast<unsigned long>(sizeof(xsai_input_arena)),
         reinterpret_cast<unsigned long>(xsai_output_arena),
         static_cast<unsigned long>(sizeof(xsai_output_arena)));

  constexpr size_t counts[] = {512, 1024, 2048};
  bool passed = true;
  size_t cases = 0;
  for (const MicrobenchSpec& microbench : kMicrobenches)
    RunMicrobench(microbench);
  for (const KernelSpec& kernel : kKernels) {
    for (size_t count : counts) {
      passed &= RunCase(kernel, count);
      ++cases;
    }
  }

  printf("XSAI_DONE status=%s cases=%lu samples=%lu\n",
         passed ? "PASS" : "FAIL", static_cast<unsigned long>(cases),
         static_cast<unsigned long>(cases * XSAI_BENCH_SAMPLES));
  return passed ? 0 : 1;
}
