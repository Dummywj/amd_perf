#ifndef SOFTMAX_SIM_XSAI_PERF_COUNTERS_H_
#define SOFTMAX_SIM_XSAI_PERF_COUNTERS_H_

#include <stddef.h>
#include <stdint.h>

namespace softmax_sim::xsai {

struct HpmSnapshot {
  uint64_t cute_active_cycles;
  uint64_t cute_retired;
  uint64_t l1d_load_misses;
  uint64_t dtlb_load_misses;
  uint64_t cute_memory_requests;
};

namespace hpm_detail {

constexpr unsigned kCuteActiveCounter = 11;
constexpr unsigned kCuteRetireCounter = 12;
constexpr unsigned kL1dLoadMissCounter = 19;
constexpr unsigned kDtlbLoadMissCounter = 20;
constexpr unsigned kCuteMemoryRequestCounter = 21;

constexpr uint16_t kCuteActiveEvent = 105;
constexpr uint16_t kCuteRetireEvent = 106;
constexpr uint16_t kLoadPipeDtlbMissEvents[3] = {5, 14, 23};
constexpr uint16_t kLoadPipeL1dMissEvents[3] = {7, 16, 25};
constexpr uint16_t kCuteMemoryReadEvent = 153;
constexpr uint16_t kCuteMemoryWriteEvent = 154;

constexpr uint64_t kMachineOnlyInhibit =
    (uint64_t{1} << 61) | (uint64_t{1} << 60) |
    (uint64_t{1} << 59) | (uint64_t{1} << 58);
constexpr uint64_t kAdd = 4;

constexpr uint64_t EncodeEvents(uint16_t event0, uint16_t event1,
                                uint16_t event2, uint16_t event3,
                                uint8_t op0, uint8_t op1, uint8_t op2) {
  return kMachineOnlyInhibit | static_cast<uint64_t>(event0) |
         (static_cast<uint64_t>(event1) << 10) |
         (static_cast<uint64_t>(event2) << 20) |
         (static_cast<uint64_t>(event3) << 30) |
         (static_cast<uint64_t>(op0) << 40) |
         (static_cast<uint64_t>(op1) << 45) |
         (static_cast<uint64_t>(op2) << 50);
}

constexpr uint64_t EncodeSingle(uint16_t event) {
  return EncodeEvents(event, 0, 0, 0, 0, 0, 0);
}

constexpr uint64_t EncodeSumTwo(uint16_t event0, uint16_t event1) {
  return EncodeEvents(event0, event1, 0, 0, kAdd, kAdd, kAdd);
}

constexpr uint64_t EncodeSumThree(uint16_t event0, uint16_t event1,
                                  uint16_t event2) {
  return EncodeEvents(event0, event1, event2, 0, kAdd, kAdd, kAdd);
}

constexpr uint64_t kTargetCounterMask =
    (uint64_t{1} << kCuteActiveCounter) |
    (uint64_t{1} << kCuteRetireCounter) |
    (uint64_t{1} << kL1dLoadMissCounter) |
    (uint64_t{1} << kDtlbLoadMissCounter) |
    (uint64_t{1} << kCuteMemoryRequestCounter);

static_assert(EncodeSingle(kCuteActiveEvent) == 0x3c00000000000069ULL);
static_assert(EncodeSingle(kCuteRetireEvent) == 0x3c0000000000006aULL);
static_assert(EncodeSumThree(kLoadPipeL1dMissEvents[0],
                            kLoadPipeL1dMissEvents[1],
                            kLoadPipeL1dMissEvents[2]) ==
              0x3c10840001904007ULL);
static_assert(EncodeSumThree(kLoadPipeDtlbMissEvents[0],
                            kLoadPipeDtlbMissEvents[1],
                            kLoadPipeDtlbMissEvents[2]) ==
              0x3c10840001703805ULL);
static_assert(EncodeSumTwo(kCuteMemoryReadEvent, kCuteMemoryWriteEvent) ==
              0x3c10840000026899ULL);

}  // namespace hpm_detail

// Takes ownership of counters 11, 12, and 19-21, clears them, and enables
// counting in M-mode. Call once before warm-up and timed measurements.
void InitializeHpmCounters();

// The fences in these calls delimit memory activity around the timed region.
HpmSnapshot BeginTimedRegionHpm();
HpmSnapshot EndTimedRegionHpm();
HpmSnapshot SubtractHpmSnapshots(const HpmSnapshot& end,
                                 const HpmSnapshot& begin);

bool CutePathInactive(const HpmSnapshot& delta);
void PrintHpmAudit(const char* scope, size_t count, int sample,
                   const HpmSnapshot& delta);

}  // namespace softmax_sim::xsai

#endif  // SOFTMAX_SIM_XSAI_PERF_COUNTERS_H_
