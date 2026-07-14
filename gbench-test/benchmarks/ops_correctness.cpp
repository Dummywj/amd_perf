#include "ops_common.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <string>
#include <vector>

namespace {

constexpr std::array<std::size_t, 14> kSizes = {
    1,          7,          15,          17,          1003,
    1ULL << 10, 1ULL << 12, 1ULL << 14,  1ULL << 16,  1ULL << 18,
    1ULL << 20, 1ULL << 22, 1ULL << 24,  1ULL << 26};
constexpr std::array<ops::Pattern, 4> kPatterns = {
    ops::Pattern::kSequential, ops::Pattern::kStride17,
    ops::Pattern::kBlockRandom4k, ops::Pattern::kUniformRandom};

std::uint32_t FloatBits(float value) {
  std::uint32_t bits;
  std::memcpy(&bits, &value, sizeof(bits));
  return bits;
}

struct Reporter {
  explicit Reporter(const std::string& path) : output(path) {
    output << "# FP32 operations correctness\n\n"
           << "- Global seed: `20260714`\n"
           << "- Sizes: tail-only 1, 7, 15, 17, 1003 plus all nine main "
              "performance sizes\n"
           << "- Status: generated before formal performance collection\n\n";
  }

  void Failure(const std::string& message) {
    ok = false;
    output << "\n**FAIL:** " << message << "\n";
  }

  std::ofstream output;
  bool ok = true;
};

void CheckReduce(Reporter* reporter) {
  reporter->output
      << "## Reduce\n\n"
      << "| N | Impl | Sum abs error | Sum relative error | Sum normalized "
         "error | Max exact | Status |\n"
      << "| ---: | --- | ---: | ---: | ---: | --- | --- |\n";
  for (const std::size_t n : kSizes) {
    ops::FloatBuffer input(n);
    ops::FillInput(input.data(), n, ops::DeriveSeed("reduce_sum", "none", n));
    double reference = 0.0;
    double sum_abs = 0.0;
    float max_reference = -std::numeric_limits<float>::infinity();
    for (std::size_t i = 0; i < n; ++i) {
      reference += static_cast<double>(input.data()[i]);
      sum_abs += std::abs(static_cast<double>(input.data()[i]));
      max_reference = std::max(max_reference, input.data()[i]);
    }
    for (const bool avx512 : {false, true}) {
      const float sum = avx512 ? ops::reduce_sum_avx512(input.data(), n)
                               : ops::reduce_sum_scalar(input.data(), n);
      const float maximum = avx512 ? ops::reduce_max_avx512(input.data(), n)
                                   : ops::reduce_max_scalar(input.data(), n);
      const double absolute = std::abs(static_cast<double>(sum) - reference);
      const double relative = absolute / std::max(std::abs(reference), 1e-300);
      const double normalized = absolute / std::max(sum_abs, 1.0);
      const bool max_exact = FloatBits(maximum) == FloatBits(max_reference);
      const bool pass = normalized <= 5e-6 && max_exact;
      reporter->output << "| " << n << " | "
                       << (avx512 ? "avx512" : "scalar") << " | "
                       << std::scientific << std::setprecision(6) << absolute
                       << " | " << relative << " | " << normalized << " | "
                       << (max_exact ? "yes" : "no") << " | "
                       << (pass ? "PASS" : "FAIL") << " |\n";
      if (!pass) {
        reporter->Failure("reduce correctness at N=" + std::to_string(n) +
                          ", impl=" + (avx512 ? "avx512" : "scalar"));
      }
    }
  }
  reporter->output << "\nThreshold: normalized sum error <= `5e-6`; max "
                      "requires FP32 exact equality.\n\n";
}

void CheckSoftmax(Reporter* reporter) {
  reporter->output
      << "## Softmax\n\n"
      << "| N | Impl | Max abs error | L1 error | Output sum error | "
         "Finite/nonnegative | Status |\n"
      << "| ---: | --- | ---: | ---: | ---: | --- | --- |\n";
  for (const std::size_t n : kSizes) {
    ops::FloatBuffer input(n), output(n);
    ops::FillInput(input.data(), n, ops::DeriveSeed("softmax", "input", n),
                   -10.0f, 10.0f);
    float input_max = input.data()[0];
    for (std::size_t i = 1; i < n; ++i) {
      input_max = std::max(input_max, input.data()[i]);
    }
    std::vector<double> reference(n);
    double reference_sum = 0.0;
    for (std::size_t i = 0; i < n; ++i) {
      reference[i] =
          std::exp(static_cast<double>(input.data()[i] - input_max));
      reference_sum += reference[i];
    }
    for (double& value : reference) {
      value /= reference_sum;
    }
    for (const bool avx512 : {false, true}) {
      (avx512 ? ops::softmax_avx512 : ops::softmax_scalar)(
          input.data(), output.data(), n);
      double max_abs = 0.0;
      double l1 = 0.0;
      double output_sum = 0.0;
      bool valid = true;
      for (std::size_t i = 0; i < n; ++i) {
        valid = valid && std::isfinite(output.data()[i]) &&
                output.data()[i] >= 0.0f;
        const double error =
            std::abs(static_cast<double>(output.data()[i]) - reference[i]);
        max_abs = std::max(max_abs, error);
        l1 += error;
        output_sum += static_cast<double>(output.data()[i]);
      }
      const double sum_error = std::abs(output_sum - 1.0);
      const bool pass = valid && max_abs <= 2e-6 && l1 <= 5e-4 &&
                        sum_error <= 5e-4;
      reporter->output << "| " << n << " | "
                       << (avx512 ? "avx512" : "scalar") << " | "
                       << std::scientific << std::setprecision(6) << max_abs
                       << " | " << l1 << " | " << sum_error << " | "
                       << (valid ? "yes" : "no") << " | "
                       << (pass ? "PASS" : "FAIL") << " |\n";
      if (!pass) {
        reporter->Failure("softmax correctness at N=" + std::to_string(n) +
                          ", impl=" + (avx512 ? "avx512" : "scalar"));
      }
    }
  }
  reporter->output
      << "\nThresholds: max absolute error <= `2e-6`, L1 error <= "
         "`5e-4`, output sum error <= `5e-4`.\n\n";
}

void CheckGather(Reporter* reporter) {
  reporter->output << "## Gather\n\n"
                   << "| N | Pattern | Permutation | Scalar | AVX-512 |\n"
                   << "| ---: | --- | --- | --- | --- |\n";
  for (const std::size_t n : kSizes) {
    ops::FloatBuffer table(n), reference(n), output(n);
    ops::IndexBuffer index(n);
    ops::FillInput(table.data(), n, ops::DeriveSeed("gather", "table", n));
    for (const ops::Pattern pattern : kPatterns) {
      if (pattern == ops::Pattern::kStride17 &&
          std::gcd<std::size_t>(17, n) != 1) {
        reporter->output << "| " << n << " | " << ops::PatternName(pattern)
                         << " | N/A (gcd(17, N) != 1) | N/A | N/A |\n";
        continue;
      }
      ops::BuildIndices(index.data(), n, pattern,
                        ops::DeriveSeed("gather", ops::PatternName(pattern), n));
      std::string permutation_error;
      const bool permutation =
          ops::ValidatePermutation(index.data(), n, &permutation_error);
      for (std::size_t i = 0; i < n; ++i) {
        reference.data()[i] = table.data()[index.data()[i]];
      }
      bool implementation_ok[2] = {true, true};
      for (int implementation = 0; implementation < 2; ++implementation) {
        (implementation ? ops::gather_avx512 : ops::gather_scalar)(
            table.data(), index.data(), output.data(), n);
        for (std::size_t i = 0; i < n; ++i) {
          if (FloatBits(output.data()[i]) != FloatBits(reference.data()[i])) {
            implementation_ok[implementation] = false;
            break;
          }
        }
      }
      reporter->output << "| " << n << " | " << ops::PatternName(pattern)
                       << " | " << (permutation ? "PASS" : "FAIL") << " | "
                       << (implementation_ok[0] ? "PASS" : "FAIL") << " | "
                       << (implementation_ok[1] ? "PASS" : "FAIL") << " |\n";
      if (!permutation || !implementation_ok[0] || !implementation_ok[1]) {
        reporter->Failure("gather correctness at N=" + std::to_string(n) +
                          ", pattern=" + ops::PatternName(pattern) +
                          (permutation_error.empty()
                               ? ""
                               : ", " + permutation_error));
      }
    }
  }
  reporter->output << "\nOutputs require FP32 bitwise equality.\n\n";
}

void CheckScatter(Reporter* reporter) {
  reporter->output << "## Scatter\n\n"
                   << "| N | Pattern | Permutation | Scalar | AVX-512 |\n"
                   << "| ---: | --- | --- | --- | --- |\n";
  for (const std::size_t n : kSizes) {
    ops::FloatBuffer source(n), reference(n), output(n);
    ops::IndexBuffer index(n);
    ops::FillInput(source.data(), n,
                   ops::DeriveSeed("scatter", "source", n));
    for (const ops::Pattern pattern : kPatterns) {
      if (pattern == ops::Pattern::kStride17 &&
          std::gcd<std::size_t>(17, n) != 1) {
        reporter->output << "| " << n << " | " << ops::PatternName(pattern)
                         << " | N/A (gcd(17, N) != 1) | N/A | N/A |\n";
        continue;
      }
      ops::BuildIndices(index.data(), n, pattern,
                        ops::DeriveSeed("scatter", ops::PatternName(pattern), n));
      std::string permutation_error;
      const bool permutation =
          ops::ValidatePermutation(index.data(), n, &permutation_error);
      ops::FillSentinel(reference.data(), n);
      for (std::size_t i = 0; i < n; ++i) {
        reference.data()[index.data()[i]] = source.data()[i];
      }
      bool implementation_ok[2] = {true, true};
      for (int implementation = 0; implementation < 2; ++implementation) {
        ops::FillSentinel(output.data(), n);
        (implementation ? ops::scatter_avx512 : ops::scatter_scalar)(
            source.data(), index.data(), output.data(), n);
        for (std::size_t i = 0; i < n; ++i) {
          if (FloatBits(output.data()[i]) != FloatBits(reference.data()[i])) {
            implementation_ok[implementation] = false;
            break;
          }
        }
      }
      reporter->output << "| " << n << " | " << ops::PatternName(pattern)
                       << " | " << (permutation ? "PASS" : "FAIL") << " | "
                       << (implementation_ok[0] ? "PASS" : "FAIL") << " | "
                       << (implementation_ok[1] ? "PASS" : "FAIL") << " |\n";
      if (!permutation || !implementation_ok[0] || !implementation_ok[1]) {
        reporter->Failure("scatter correctness at N=" + std::to_string(n) +
                          ", pattern=" + ops::PatternName(pattern) +
                          (permutation_error.empty()
                               ? ""
                               : ", " + permutation_error));
      }
    }
  }
  reporter->output << "\nFull destination buffers require FP32 bitwise "
                      "equality after sentinel initialization.\n\n";
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: ops_correctness <output.md>\n";
    return 2;
  }
  Reporter reporter(argv[1]);
  if (!reporter.output) {
    std::cerr << "cannot open output: " << argv[1] << "\n";
    return 2;
  }
  CheckReduce(&reporter);
  CheckGather(&reporter);
  CheckScatter(&reporter);
  CheckSoftmax(&reporter);
  reporter.output << "## Final status\n\n**"
                  << (reporter.ok ? "PASS" : "FAIL") << "**\n";
  return reporter.ok ? 0 : 1;
}
