#pragma once

namespace softmax_sim::kernel::softmax {

inline constexpr float kExpInputMin = -0x1.5cp+6f;  // -87.0f
inline constexpr float kLog2E = 0x1.715476p+0f;
inline constexpr float kLn2 = 0x1.62e43p-1f;

inline constexpr float kExpC7 = 0x1.a01a02p-13f;
inline constexpr float kExpC6 = 0x1.6c16c2p-10f;
inline constexpr float kExpC5 = 0x1.111112p-7f;
inline constexpr float kExpC4 = 0x1.555556p-5f;
inline constexpr float kExpC3 = 0x1.555556p-3f;
inline constexpr float kExpC2 = 0x1p-1f;
inline constexpr float kExpC1 = 0x1p+0f;
inline constexpr float kExpC0 = 0x1p+0f;

}  // namespace softmax_sim::kernel::softmax
