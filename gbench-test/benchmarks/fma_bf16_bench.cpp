#include "fma_bf16.h"

namespace {
const bool kRegistered = [] {
  bf16_fma::RegisterBenchmarks();
  return true;
}();
}  // namespace

BENCHMARK_MAIN();
