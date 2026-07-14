#include "ops_common.h"

namespace {
const bool kRegistered = [] {
  ops::RegisterSoftmaxBenchmarks();
  return true;
}();
}  // namespace

BENCHMARK_MAIN();
