#pragma once

#include <bit>
#include <cstdint>

#include "softmax_constants.h"

namespace softmax_sim::kernel::softmax {

inline float ExpApproxScalar(float value) {
  value = value < kExpInputMin ? kExpInputMin : value;
  value = value > 0.0f ? 0.0f : value;

  const std::int32_t exponent =
      static_cast<std::int32_t>(value * kLog2E);
  const float reduced = value - static_cast<float>(exponent) * kLn2;

  float polynomial = kExpC7;
  polynomial = polynomial * reduced + kExpC6;
  polynomial = polynomial * reduced + kExpC5;
  polynomial = polynomial * reduced + kExpC4;
  polynomial = polynomial * reduced + kExpC3;
  polynomial = polynomial * reduced + kExpC2;
  polynomial = polynomial * reduced + kExpC1;
  polynomial = polynomial * reduced + kExpC0;

  const std::uint32_t exponent_bits =
      static_cast<std::uint32_t>(exponent + 127) << 23;
  return polynomial * std::bit_cast<float>(exponent_bits);
}

}  // namespace softmax_sim::kernel::softmax
