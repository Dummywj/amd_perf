#pragma once

#include <asm/unistd.h>
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <cerrno>
#include <cstdint>
#include <cstring>
#include <string>

class PerfCounter {
 public:
  static PerfCounter OpenUserCoreCycles() {
    perf_event_attr attr{};
    attr.type = PERF_TYPE_HARDWARE;
    attr.size = sizeof(attr);
    attr.config = PERF_COUNT_HW_CPU_CYCLES;
    attr.disabled = 1;
    attr.exclude_kernel = 1;
    attr.exclude_hv = 1;

    const int fd = static_cast<int>(
        syscall(__NR_perf_event_open, &attr, 0, -1, -1, 0));
    if (fd == -1) {
      return PerfCounter("perf_event_open(PERF_COUNT_HW_CPU_CYCLES) failed: " +
                         std::string(std::strerror(errno)));
    }

    return PerfCounter(fd);
  }

  PerfCounter(PerfCounter&& other) noexcept
      : fd_(other.fd_), error_(std::move(other.error_)) {
    other.fd_ = -1;
  }

  PerfCounter& operator=(PerfCounter&& other) noexcept {
    if (this != &other) {
      Close();
      fd_ = other.fd_;
      error_ = std::move(other.error_);
      other.fd_ = -1;
    }
    return *this;
  }

  PerfCounter(const PerfCounter&) = delete;
  PerfCounter& operator=(const PerfCounter&) = delete;

  ~PerfCounter() { Close(); }

  bool ok() const { return fd_ >= 0; }
  const std::string& error() const { return error_; }

  bool Start(std::string* error) {
    if (!Reset(error)) {
      return false;
    }
    if (ioctl(fd_, PERF_EVENT_IOC_ENABLE, 0) == -1) {
      *error = "PERF_EVENT_IOC_ENABLE failed: " +
               std::string(std::strerror(errno));
      return false;
    }
    return true;
  }

  bool Stop(std::uint64_t* value, std::string* error) {
    if (ioctl(fd_, PERF_EVENT_IOC_DISABLE, 0) == -1) {
      *error = "PERF_EVENT_IOC_DISABLE failed: " +
               std::string(std::strerror(errno));
      return false;
    }

    const ssize_t bytes = read(fd_, value, sizeof(*value));
    if (bytes != static_cast<ssize_t>(sizeof(*value))) {
      *error = "read(perf counter) failed: " + std::string(std::strerror(errno));
      return false;
    }
    return true;
  }

 private:
  explicit PerfCounter(int fd) : fd_(fd) {}
  explicit PerfCounter(std::string error) : error_(std::move(error)) {}

  bool Reset(std::string* error) {
    if (ioctl(fd_, PERF_EVENT_IOC_RESET, 0) == -1) {
      *error = "PERF_EVENT_IOC_RESET failed: " +
               std::string(std::strerror(errno));
      return false;
    }
    return true;
  }

  void Close() {
    if (fd_ >= 0) {
      close(fd_);
      fd_ = -1;
    }
  }

  int fd_ = -1;
  std::string error_;
};

