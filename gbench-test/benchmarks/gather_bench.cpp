#include "ops_common.h"

namespace {
const bool kRegistered = [] {
  ops::RegisterGatherBenchmarks();
  return true;
}();
}  // namespace

BENCHMARK_MAIN();
