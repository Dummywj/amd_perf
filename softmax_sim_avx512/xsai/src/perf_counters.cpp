#include "perf_counters.h"

#include <klib.h>

#if !defined(__riscv) || (__riscv_xlen != 64)
#error "XSAI HPM access requires RV64"
#endif

namespace softmax_sim::xsai {
namespace {

#define XSAI_DEFINE_CSR_ACCESSORS(name)                                  \
  inline uint64_t Read_##name() {                                       \
    uint64_t value;                                                      \
    asm volatile("csrr %0, " #name : "=r"(value) : : "memory");       \
    return value;                                                        \
  }                                                                      \
  inline void Write_##name(uint64_t value) {                             \
    asm volatile("csrw " #name ", %0" : : "r"(value) : "memory");    \
  }

XSAI_DEFINE_CSR_ACCESSORS(mcountinhibit)
XSAI_DEFINE_CSR_ACCESSORS(mhpmevent11)
XSAI_DEFINE_CSR_ACCESSORS(mhpmevent12)
XSAI_DEFINE_CSR_ACCESSORS(mhpmevent19)
XSAI_DEFINE_CSR_ACCESSORS(mhpmevent20)
XSAI_DEFINE_CSR_ACCESSORS(mhpmevent21)
XSAI_DEFINE_CSR_ACCESSORS(mhpmcounter11)
XSAI_DEFINE_CSR_ACCESSORS(mhpmcounter12)
XSAI_DEFINE_CSR_ACCESSORS(mhpmcounter19)
XSAI_DEFINE_CSR_ACCESSORS(mhpmcounter20)
XSAI_DEFINE_CSR_ACCESSORS(mhpmcounter21)

#undef XSAI_DEFINE_CSR_ACCESSORS

inline void MeasurementFence() {
  asm volatile("fence rw, rw" : : : "memory");
}

inline void DrainHpmPipeline() {
  // LoadUnit, HPerfCounter, HPerfMonitor, and MemBlock each register events.
  asm volatile(".rept 16\n\tnop\n\t.endr" : : : "memory");
}

HpmSnapshot ReadHpmSnapshot() {
  return {
      .cute_active_cycles = Read_mhpmcounter11(),
      .cute_retired = Read_mhpmcounter12(),
      .l1d_load_misses = Read_mhpmcounter19(),
      .dtlb_load_misses = Read_mhpmcounter20(),
      .cute_memory_requests = Read_mhpmcounter21(),
  };
}

}  // namespace

void InitializeHpmCounters() {
  using namespace hpm_detail;
  const uint64_t previous_inhibit = Read_mcountinhibit();
  Write_mcountinhibit(previous_inhibit | kTargetCounterMask);

  Write_mhpmevent11(EncodeSingle(kCuteActiveEvent));
  Write_mhpmevent12(EncodeSingle(kCuteRetireEvent));
  Write_mhpmevent19(EncodeSumThree(kLoadPipeL1dMissEvents[0],
                                   kLoadPipeL1dMissEvents[1],
                                   kLoadPipeL1dMissEvents[2]));
  Write_mhpmevent20(EncodeSumThree(kLoadPipeDtlbMissEvents[0],
                                   kLoadPipeDtlbMissEvents[1],
                                   kLoadPipeDtlbMissEvents[2]));
  Write_mhpmevent21(
      EncodeSumTwo(kCuteMemoryReadEvent, kCuteMemoryWriteEvent));

  Write_mhpmcounter11(0);
  Write_mhpmcounter12(0);
  Write_mhpmcounter19(0);
  Write_mhpmcounter20(0);
  Write_mhpmcounter21(0);
  MeasurementFence();
  DrainHpmPipeline();
  Write_mcountinhibit(previous_inhibit & ~kTargetCounterMask);
  MeasurementFence();
}

HpmSnapshot BeginTimedRegionHpm() {
  MeasurementFence();
  DrainHpmPipeline();
  return ReadHpmSnapshot();
}

HpmSnapshot EndTimedRegionHpm() {
  MeasurementFence();
  DrainHpmPipeline();
  return ReadHpmSnapshot();
}

HpmSnapshot SubtractHpmSnapshots(const HpmSnapshot& end,
                                 const HpmSnapshot& begin) {
  return {
      .cute_active_cycles = end.cute_active_cycles - begin.cute_active_cycles,
      .cute_retired = end.cute_retired - begin.cute_retired,
      .l1d_load_misses = end.l1d_load_misses - begin.l1d_load_misses,
      .dtlb_load_misses = end.dtlb_load_misses - begin.dtlb_load_misses,
      .cute_memory_requests =
          end.cute_memory_requests - begin.cute_memory_requests,
  };
}

bool CutePathInactive(const HpmSnapshot& delta) {
  return delta.cute_active_cycles == 0 && delta.cute_retired == 0 &&
         delta.cute_memory_requests == 0;
}

void PrintHpmAudit(const char* scope, size_t count, int sample,
                   const HpmSnapshot& delta) {
  const bool cache_clean =
      delta.l1d_load_misses == 0 && delta.dtlb_load_misses == 0;
  printf(
      "XSAI_HPM scope=%s n=%lu sample=%d cute_active_cycles=%lu "
      "cute_retired=%lu cute_memory_requests=%lu l1d_load_misses=%lu "
      "dtlb_load_misses=%lu cute_status=%s cache_status=%s\n",
      scope, static_cast<unsigned long>(count), sample,
      static_cast<unsigned long>(delta.cute_active_cycles),
      static_cast<unsigned long>(delta.cute_retired),
      static_cast<unsigned long>(delta.cute_memory_requests),
      static_cast<unsigned long>(delta.l1d_load_misses),
      static_cast<unsigned long>(delta.dtlb_load_misses),
      CutePathInactive(delta) ? "PASS" : "FAIL",
      cache_clean ? "CLEAN" : "CONTAMINATED");
}

}  // namespace softmax_sim::xsai
