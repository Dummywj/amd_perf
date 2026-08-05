#pragma once

#include <asm/unistd.h>
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <cerrno>
#include <cstdint>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

namespace amd_profile {

struct EventSpec {
  std::string name;
  std::uint32_t type;
  std::uint64_t config;
};

struct EventValue {
  std::string name;
  double value;
};

constexpr std::uint64_t RawConfig(std::uint16_t event,
                                  std::uint8_t unit_mask) {
  return static_cast<std::uint64_t>(event) |
         (static_cast<std::uint64_t>(unit_mask) << 8);
}

inline EventSpec CoreCycles() {
  return {"core_cycles", PERF_TYPE_HARDWARE, PERF_COUNT_HW_CPU_CYCLES};
}

inline EventSpec RawEvent(const char* name, std::uint16_t event,
                          std::uint8_t unit_mask) {
  return {name, PERF_TYPE_RAW, RawConfig(event, unit_mask)};
}

class PerfEventGroup {
 public:
  static PerfEventGroup Open(std::vector<EventSpec> specs) {
    PerfEventGroup group(std::move(specs));
    if (group.specs_.empty()) {
      group.error_ = "perf event group is empty";
      return group;
    }

    int leader = -1;
    for (const auto& spec : group.specs_) {
      perf_event_attr attr{};
      attr.type = spec.type;
      attr.size = sizeof(attr);
      attr.config = spec.config;
      attr.disabled = leader == -1 ? 1 : 0;
      attr.exclude_kernel = 1;
      attr.exclude_hv = 1;
      attr.read_format = PERF_FORMAT_GROUP | PERF_FORMAT_TOTAL_TIME_ENABLED |
                         PERF_FORMAT_TOTAL_TIME_RUNNING;

      const int fd = static_cast<int>(
          syscall(__NR_perf_event_open, &attr, 0, -1, leader, 0));
      if (fd == -1) {
        group.error_ = "perf_event_open(" + spec.name + ") failed: " +
                       std::string(std::strerror(errno));
        group.Close();
        return group;
      }
      if (leader == -1) {
        leader = fd;
        group.leader_fd_ = fd;
      }
      group.fds_.push_back(fd);
    }
    return group;
  }

  PerfEventGroup(PerfEventGroup&& other) noexcept
      : specs_(std::move(other.specs_)),
        fds_(std::move(other.fds_)),
        leader_fd_(other.leader_fd_),
        error_(std::move(other.error_)) {
    other.leader_fd_ = -1;
    other.fds_.clear();
  }

  PerfEventGroup& operator=(PerfEventGroup&& other) noexcept {
    if (this != &other) {
      Close();
      specs_ = std::move(other.specs_);
      fds_ = std::move(other.fds_);
      leader_fd_ = other.leader_fd_;
      error_ = std::move(other.error_);
      other.leader_fd_ = -1;
      other.fds_.clear();
    }
    return *this;
  }

  PerfEventGroup(const PerfEventGroup&) = delete;
  PerfEventGroup& operator=(const PerfEventGroup&) = delete;

  ~PerfEventGroup() { Close(); }

  bool ok() const { return leader_fd_ >= 0; }
  const std::string& error() const { return error_; }

  bool Start(std::string* error) {
    if (ioctl(leader_fd_, PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP) == -1 ||
        ioctl(leader_fd_, PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP) == -1) {
      *error = "enable perf event group failed: " +
               std::string(std::strerror(errno));
      return false;
    }
    return true;
  }

  bool Stop(std::vector<EventValue>* values, double* running_ratio,
            std::string* error) {
    if (ioctl(leader_fd_, PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP) == -1) {
      *error = "disable perf event group failed: " +
               std::string(std::strerror(errno));
      return false;
    }

    std::vector<std::uint64_t> buffer(3 + specs_.size());
    const ssize_t expected =
        static_cast<ssize_t>(buffer.size() * sizeof(std::uint64_t));
    const ssize_t bytes = read(leader_fd_, buffer.data(), expected);
    if (bytes != expected || buffer[0] != specs_.size()) {
      *error = "read perf event group failed: " +
               std::string(std::strerror(errno));
      return false;
    }

    const double enabled = static_cast<double>(buffer[1]);
    const double running = static_cast<double>(buffer[2]);
    if (enabled <= 0.0 || running <= 0.0) {
      *error = "perf event group reported zero running time";
      return false;
    }
    const double scale = enabled / running;
    *running_ratio = running / enabled;
    values->clear();
    for (std::size_t i = 0; i < specs_.size(); ++i) {
      values->push_back(
          {specs_[i].name, static_cast<double>(buffer[3 + i]) * scale});
    }
    return true;
  }

 private:
  explicit PerfEventGroup(std::vector<EventSpec> specs)
      : specs_(std::move(specs)) {}

  void Close() {
    for (int fd : fds_) {
      if (fd >= 0) {
        close(fd);
      }
    }
    fds_.clear();
    leader_fd_ = -1;
  }

  std::vector<EventSpec> specs_;
  std::vector<int> fds_;
  int leader_fd_ = -1;
  std::string error_;
};

}  // namespace amd_profile
