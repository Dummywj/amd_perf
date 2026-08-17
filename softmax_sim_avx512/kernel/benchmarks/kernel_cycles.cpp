#include "common/kernel_registry.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <immintrin.h>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "perf_event_group.h"

namespace {

template <typename T>
class AlignedBuffer {
 public:
  explicit AlignedBuffer(std::size_t count) {
    void* storage = nullptr;
    if (posix_memalign(&storage, 4096, count * sizeof(T)) != 0) {
      throw std::bad_alloc();
    }
    data_.reset(static_cast<T*>(storage));
  }
  T* data() { return data_.get(); }
  T& operator[](std::size_t index) { return data_.get()[index]; }

 private:
  struct FreeDeleter {
    void operator()(T* pointer) const { std::free(pointer); }
  };
  std::unique_ptr<T, FreeDeleter> data_;
};

__attribute__((noinline)) void EmptyKernel(const float* input, float* output,
                                           std::size_t count) {
  asm volatile("" : : "r"(input), "r"(output), "r"(count) : "memory");
}

double FindEvent(const std::vector<amd_profile::EventValue>& values,
                 const std::string& name) {
  const auto found = std::find_if(
      values.begin(), values.end(),
      [&](const auto& value) { return value.name == name; });
  return found == values.end() ? 0.0 : found->value;
}

struct Measurement {
  double cycles;
  double instructions;
  double branches;
  double cache_misses;
  double running_ratio;
};

Measurement Measure(KernelF32 kernel, const float* input, float* output,
                    std::size_t count, std::uint64_t calls) {
  auto events = amd_profile::PerfEventGroup::Open({
      amd_profile::CoreCycles(),
      {"instructions", PERF_TYPE_HARDWARE, PERF_COUNT_HW_INSTRUCTIONS},
      {"branches", PERF_TYPE_HARDWARE, PERF_COUNT_HW_BRANCH_INSTRUCTIONS},
      {"cache_misses", PERF_TYPE_HARDWARE, PERF_COUNT_HW_CACHE_MISSES},
  });
  if (!events.ok()) throw std::runtime_error(events.error());
  std::string error;
  if (!events.Start(&error)) throw std::runtime_error(error);
  for (std::uint64_t call = 0; call < calls; ++call) {
    _mm_lfence();
    kernel(input, output, count);
    _mm_lfence();
  }
  std::vector<amd_profile::EventValue> values;
  double ratio = 0.0;
  if (!events.Stop(&values, &ratio, &error)) throw std::runtime_error(error);
  if (ratio < 0.95) throw std::runtime_error("PMU running ratio below 0.95");
  return {
      FindEvent(values, "core_cycles") / calls,
      FindEvent(values, "instructions") / calls,
      FindEvent(values, "branches") / calls,
      FindEvent(values, "cache_misses") / calls,
      ratio,
  };
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const std::string selected = argc > 1 ? argv[1] : "all";
    const int repetitions = argc > 2 ? std::stoi(argv[2]) : 7;
    if (repetitions < 1) throw std::invalid_argument("repetitions must be positive");
    constexpr std::size_t kMaximumCount = 2048;
    AlignedBuffer<float> input(kMaximumCount * 3);
    AlignedBuffer<float> output(kMaximumCount);
    for (std::size_t index = 0; index < kMaximumCount * 3; ++index) {
      input[index] = static_cast<float>(static_cast<int>(index % 257) - 128) *
                     0.03125f;
    }
    std::cout << std::setprecision(12) << "{\n  \"format_version\":1,\n"
              << "  \"repetitions\":" << repetitions
              << ",\n  \"measurements\":[\n";
    bool first = true;
    for (const KernelSpec& spec : kKernelSpecs) {
      if (selected != "all" && selected != spec.name) continue;
      for (std::size_t count : {512U, 1024U, 2048U}) {
        const std::uint64_t calls =
            std::max<std::uint64_t>(1024, (2ULL * 1024 * 1024) / count);
        for (int warmup = 0; warmup < 32; ++warmup)
          spec.avx512(input.data(), output.data(), count);
        for (int repetition = 0; repetition < repetitions; ++repetition) {
          Measurement baseline;
          Measurement kernel;
          if ((repetition & 1) == 0) {
            kernel = Measure(spec.avx512, input.data(), output.data(), count, calls);
            baseline = Measure(EmptyKernel, input.data(), output.data(), count, calls);
          } else {
            baseline = Measure(EmptyKernel, input.data(), output.data(), count, calls);
            kernel = Measure(spec.avx512, input.data(), output.data(), count, calls);
          }
          if (!first) std::cout << ",\n";
          first = false;
          std::cout << "    {\"kernel\":\"" << spec.name << "\",\"count\":"
                    << count << ",\"repetition\":" << repetition
                    << ",\"calls\":" << calls
                    << ",\"cycles_per_call\":" << kernel.cycles
                    << ",\"baseline_cycles\":" << baseline.cycles
                    << ",\"net_cycles\":" << kernel.cycles - baseline.cycles
                    << ",\"instructions_per_call\":" << kernel.instructions
                    << ",\"branches_per_call\":" << kernel.branches
                    << ",\"cache_misses_per_call\":" << kernel.cache_misses
                    << ",\"pmu_running_ratio\":"
                    << std::min(kernel.running_ratio, baseline.running_ratio) << "}";
        }
      }
    }
    std::cout << "\n  ]\n}\n";
  } catch (const std::exception& error) {
    std::cerr << "kernel_cycles: " << error.what() << '\n';
    return 2;
  }
  return 0;
}
