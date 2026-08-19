#include "perf_counters.h"

#include <am.h>
#include <klib.h>

int main(const char*) {
  using namespace softmax_sim::xsai;
  InitializeHpmCounters();
  const HpmSnapshot begin = BeginTimedRegionHpm();
  volatile unsigned long accumulator = 0;
  for (unsigned long index = 0; index < 64; ++index) accumulator += index;
  const HpmSnapshot end = EndTimedRegionHpm();
  const HpmSnapshot delta = SubtractHpmSnapshots(end, begin);
  PrintHpmAudit("csr_smoke", 64, 0, delta);
  const bool passed = accumulator == 2016 && CutePathInactive(delta);
  printf("XSAI_HPM_SMOKE status=%s\n", passed ? "PASS" : "FAIL");
  return passed ? 0 : 1;
}
