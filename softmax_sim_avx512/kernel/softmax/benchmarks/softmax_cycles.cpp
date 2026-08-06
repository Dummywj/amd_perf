#include "common/softmax_interface.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <immintrin.h>
#include <iostream>
#include <numeric>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

#include "perf_event_group.h"

namespace {

using Kernel = void (*)(const float*, float*, std::size_t);

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

double FindEvent(const std::vector<amd_profile::EventValue>& values,
                 const std::string& name) {
  const auto found = std::find_if(
      values.begin(), values.end(),
      [&](const amd_profile::EventValue& value) { return value.name == name; });
  return found == values.end() ? 0.0 : found->value;
}

__attribute__((noinline)) void EmptyKernel(const float* input, float* output,
                                           std::size_t count) {
  asm volatile("" : : "r"(input), "r"(output), "r"(count) : "memory");
}

struct Measurement {
  std::size_t count;
  int repetition;
  std::uint64_t calls;
  std::string kind;
  double cycles;
  double instructions;
  double branches;
  double cache_misses;
  double running_ratio;
};

Measurement Measure(Kernel kernel, const std::string& kind,
                    const float* input, float* output, std::size_t count,
                    int repetition, std::uint64_t calls, bool serialized) {
  auto events = amd_profile::PerfEventGroup::Open({
      amd_profile::CoreCycles(),
      {"instructions", PERF_TYPE_HARDWARE, PERF_COUNT_HW_INSTRUCTIONS},
      {"branches", PERF_TYPE_HARDWARE, PERF_COUNT_HW_BRANCH_INSTRUCTIONS},
      {"cache_misses", PERF_TYPE_HARDWARE, PERF_COUNT_HW_CACHE_MISSES},
  });
  if (!events.ok()) {
    throw std::runtime_error(events.error());
  }
  std::string error;
  if (!events.Start(&error)) {
    throw std::runtime_error(error);
  }
  for (std::uint64_t call = 0; call < calls; ++call) {
    if (serialized) {
      _mm_lfence();
    }
    kernel(input, output, count);
    if (serialized) {
      _mm_lfence();
    }
  }
  std::vector<amd_profile::EventValue> values;
  double running_ratio = 0.0;
  if (!events.Stop(&values, &running_ratio, &error)) {
    throw std::runtime_error(error);
  }
  return {
      count,
      repetition,
      calls,
      kind,
      FindEvent(values, "core_cycles") / calls,
      FindEvent(values, "instructions") / calls,
      FindEvent(values, "branches") / calls,
      FindEvent(values, "cache_misses") / calls,
      running_ratio,
  };
}

void PrintMeasurement(const Measurement& value, bool last) {
  std::cout << "    {\"count\":" << value.count
            << ",\"repetition\":" << value.repetition
            << ",\"calls\":" << value.calls << ",\"kind\":\""
            << value.kind << "\",\"cycles_per_call\":" << value.cycles
            << ",\"instructions_per_call\":" << value.instructions
            << ",\"branches_per_call\":" << value.branches
            << ",\"cache_misses_per_call\":" << value.cache_misses
            << ",\"pmu_running_ratio\":" << value.running_ratio << "}"
            << (last ? "\n" : ",\n");
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const int repetitions = argc > 1 ? std::stoi(argv[1]) : 7;
    if (repetitions < 1) {
      throw std::invalid_argument("repetitions must be positive");
    }
    const std::vector<std::size_t> counts = {16,  32,  64,   128, 256,
                                             512, 1024, 2048, 4096};
    constexpr std::size_t kMaximumCount = 4096;
    AlignedBuffer<float> input(kMaximumCount);
    AlignedBuffer<float> output(kMaximumCount);
    for (std::size_t index = 0; index < kMaximumCount; ++index) {
      input[index] = std::sin(static_cast<float>(index) * 0.013f) * 8.0f;
      output[index] = 0.0f;
    }

    std::vector<std::pair<std::size_t, int>> order;
    for (int repetition = 0; repetition < repetitions; ++repetition) {
      for (std::size_t count : counts) {
        order.emplace_back(count, repetition);
      }
    }
    std::mt19937 generator(0x5A17U);
    std::shuffle(order.begin(), order.end(), generator);

    std::vector<Measurement> measurements;
    measurements.reserve(order.size() * 4);
    for (const auto& [count, repetition] : order) {
      for (int warmup = 0; warmup < 64; ++warmup) {
        softmax_avx512_f32(input.data(), output.data(), count);
      }
      const std::uint64_t calls =
          std::max<std::uint64_t>(2048, (8ULL * 1024 * 1024) / count);
      if ((repetition & 1) == 0) {
        measurements.push_back(Measure(softmax_avx512_f32, "kernel", input.data(),
                                       output.data(), count, repetition, calls, false));
        measurements.push_back(Measure(EmptyKernel, "baseline", input.data(),
                                       output.data(), count, repetition, calls, false));
      } else {
        measurements.push_back(Measure(EmptyKernel, "baseline", input.data(),
                                       output.data(), count, repetition, calls, false));
        measurements.push_back(Measure(softmax_avx512_f32, "kernel", input.data(),
                                       output.data(), count, repetition, calls, false));
      }
      measurements.push_back(Measure(
          softmax_avx512_f32, "serialized_kernel", input.data(), output.data(),
          count, repetition, calls, true));
      measurements.push_back(Measure(
          EmptyKernel, "serialized_baseline", input.data(), output.data(), count,
          repetition, calls, true));
    }

    const float checksum =
        std::accumulate(output.data(), output.data() + kMaximumCount, 0.0f);
    std::cout << std::setprecision(12)
              << "{\n  \"format_version\":1,\n  \"repetitions\":"
              << repetitions << ",\n  \"checksum\":" << checksum
              << ",\n  \"measurements\":[\n";
    for (std::size_t index = 0; index < measurements.size(); ++index) {
      PrintMeasurement(measurements[index], index + 1 == measurements.size());
    }
    std::cout << "  ]\n}\n";
  } catch (const std::exception& error) {
    std::cerr << "softmax_cycles: " << error.what() << '\n';
    return 2;
  }
  return 0;
}
