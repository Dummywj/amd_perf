#pragma once

#include <benchmark/benchmark.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <memory>
#include <string>
#include <vector>

#include "perf_event_group.h"

namespace amd_profile {

template <typename T>
class AlignedBuffer {
 public:
  explicit AlignedBuffer(std::size_t count, std::size_t alignment = 4096)
      : count_(count) {
    void* storage = nullptr;
    if (posix_memalign(&storage, alignment, count * sizeof(T)) != 0) {
      throw std::bad_alloc();
    }
    data_.reset(static_cast<T*>(storage));
  }

  T* data() { return data_.get(); }
  const T* data() const { return data_.get(); }
  std::size_t size() const { return count_; }
  T& operator[](std::size_t index) { return data_.get()[index]; }
  const T& operator[](std::size_t index) const { return data_.get()[index]; }

 private:
  struct FreeDeleter {
    void operator()(T* pointer) const { std::free(pointer); }
  };

  std::size_t count_;
  std::unique_ptr<T, FreeDeleter> data_;
};

inline bool StartEvents(benchmark::State& state, PerfEventGroup* group,
                        std::string* error) {
  if (!group->ok()) {
    state.SkipWithError(group->error().c_str());
    return false;
  }
  if (!group->Start(error)) {
    state.SkipWithError(error->c_str());
    return false;
  }
  return true;
}

inline bool StopEvents(benchmark::State& state, PerfEventGroup* group,
                       std::vector<EventValue>* values,
                       std::string* error) {
  double running_ratio = 0.0;
  if (!group->Stop(values, &running_ratio, error)) {
    state.SkipWithError(error->c_str());
    return false;
  }
  state.counters["pmu_running_ratio"] = running_ratio;
  for (const auto& value : *values) {
    state.counters[value.name] = value.value;
  }
  return true;
}

inline double FindEvent(const std::vector<EventValue>& values,
                        const std::string& name) {
  const auto found =
      std::find_if(values.begin(), values.end(), [&](const EventValue& value) {
        return value.name == name;
      });
  return found == values.end() ? 0.0 : found->value;
}

}  // namespace amd_profile
