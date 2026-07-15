#include "ops_common.h"

namespace {
const bool kRegistered = [] {
  ops::RegisterFmaBenchmarks();
  return true;
}();
}  // namespace

BENCHMARK_MAIN();
