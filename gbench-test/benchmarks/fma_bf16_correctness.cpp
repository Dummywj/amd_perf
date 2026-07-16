#include "fma_bf16.h"

#include "ops_common.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>

namespace {

constexpr std::array<std::size_t, 9> kSizes = {
    1, 2, 15, 16, 31, 32, 33, 1003, 1024};

float ReferencePair(const bf16_fma::Bf16* a, const bf16_fma::Bf16* b,
                    std::size_t n, std::size_t pair, float accumulator) {
  const std::size_t first = pair * 2;
  accumulator = std::fma(bf16_fma::Bf16ToFloat(a[first]),
                         bf16_fma::Bf16ToFloat(b[first]), accumulator);
  if (first + 1 < n) {
    accumulator = std::fma(bf16_fma::Bf16ToFloat(a[first + 1]),
                           bf16_fma::Bf16ToFloat(b[first + 1]), accumulator);
  }
  return accumulator;
}

double CheckCase(std::size_t n, bool reuse, bool* finite) {
  const std::size_t output_elements = bf16_fma::OutputElements(n);
  bf16_fma::Bf16Buffer a(n), b(n);
  ops::FloatBuffer c(output_elements), expected(output_elements),
      actual(output_elements);
  bf16_fma::FillInput(a.data(), n,
                      ops::DeriveSeed("fma_bf16_correctness", "a", n));
  bf16_fma::FillInput(b.data(), n,
                      ops::DeriveSeed("fma_bf16_correctness", "b", n));
  ops::FillInput(c.data(), output_elements,
                 ops::DeriveSeed("fma_bf16_correctness", "c", n), -0.5f,
                 0.5f);
  const int rounds = reuse ? bf16_fma::kReuseRounds : 1;
  for (std::size_t pair = 0; pair < output_elements; ++pair) {
    float value = c.data()[pair];
    for (int round = 0; round < rounds; ++round) {
      value = ReferencePair(a.data(), b.data(), n, pair, value);
    }
    expected.data()[pair] = value;
  }
  (reuse ? bf16_fma::fma_bf16_reuse_avx512_dot
         : bf16_fma::fma_bf16_once_avx512_dot)(
      a.data(), b.data(), c.data(), actual.data(), n);

  double max_error = 0.0;
  *finite = true;
  for (std::size_t i = 0; i < output_elements; ++i) {
    *finite = *finite && std::isfinite(actual.data()[i]);
    max_error = std::max(
        max_error, std::abs(static_cast<double>(actual.data()[i]) -
                            static_cast<double>(expected.data()[i])));
  }
  return max_error;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: fma_bf16_correctness <output.md>\n";
    return 2;
  }
  std::ofstream output(argv[1]);
  if (!output) {
    std::cerr << "cannot open output: " << argv[1] << "\n";
    return 2;
  }
  output << "# BF16 FMA correctness\n\n"
         << "- Required ISA: `AVX-512 BF16`\n"
         << "- Native operation: `vdpbf16ps`\n"
         << "- Odd tails treat the missing BF16 lane as zero.\n\n";
  if (!bf16_fma::IsAvx512Bf16Supported()) {
    output << "## Final status\n\n**SKIP: CPU lacks AVX-512 BF16**\n";
    std::cerr << "CPU does not support AVX-512 BF16\n";
    return 3;
  }

  bool ok = bf16_fma::FloatToBf16Rne(1.0f) == 0x3f80U &&
            bf16_fma::FloatToBf16Rne(-2.5f) == 0xc020U;
  output << "| N | Case | Max abs error | Finite | Status |\n"
         << "| ---: | --- | ---: | --- | --- |\n";
  for (const std::size_t n : kSizes) {
    for (const bool reuse : {true, false}) {
      bool finite = false;
      const double error = CheckCase(n, reuse, &finite);
      const double tolerance = reuse ? 1e-5 : 1e-6;
      const bool pass = finite && error <= tolerance;
      ok = ok && pass;
      output << "| " << n << " | " << (reuse ? "reuse (64)" : "once (1)")
             << " | " << std::scientific << std::setprecision(6) << error
             << " | " << (finite ? "yes" : "no") << " | "
             << (pass ? "PASS" : "FAIL") << " |\n";
    }
  }
  output << "\nThresholds: reuse max absolute error <= `1e-5`; once <= "
            "`1e-6`.\n\n"
         << "## Final status\n\n**" << (ok ? "PASS" : "FAIL") << "**\n";
  return ok ? 0 : 1;
}
