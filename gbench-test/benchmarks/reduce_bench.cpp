#include "ops_common.h"

namespace {
const bool kRegistered = [] {
  ops::RegisterReduceBenchmarks();
  return true;
}();
}  // namespace

BENCHMARK_MAIN();
