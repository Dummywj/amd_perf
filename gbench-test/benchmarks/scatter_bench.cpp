#include "ops_common.h"

namespace {
const bool kRegistered = [] {
  ops::RegisterScatterBenchmarks();
  return true;
}();
}  // namespace

BENCHMARK_MAIN();
