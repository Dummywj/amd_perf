#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
softmax_dir=$(cd -- "${script_dir}/.." && pwd)
artifact_dir="${softmax_dir}/artifacts"
x86_cxx=${X86_CXX:-c++}
rvv_cxx=${RVV_CXX:-riscv64-linux-gnu-g++}

mkdir -p "${artifact_dir}/x86" "${artifact_dir}/rvv"

print_flags() {
  local first=1
  local flag
  for flag in "$@"; do
    if ((first == 0)); then
      printf ' '
    fi
    printf '%s' "${flag}"
    first=0
  done
  printf '\n'
}

common_flags=(
  -std=c++20 -O3 -Wall -Wextra -Wpedantic
  -fno-stack-protector -fno-asynchronous-unwind-tables
  -fno-unwind-tables -fno-exceptions -fno-rtti -fno-pie
  -fcf-protection=none
  -I"${softmax_dir}"
)

"${x86_cxx}" "${common_flags[@]}" \
  -mavx512f -mavx512dq -mavx512bw -mavx512vl -mfma \
  -S "${softmax_dir}/x86/softmax_avx512.cpp" \
  -o "${artifact_dir}/x86/softmax_avx512.s"

"${rvv_cxx}" "${common_flags[@]}" \
  -march=rv64gcv -mabi=lp64d \
  -S "${softmax_dir}/rvv/softmax_rvv.cpp" \
  -o "${artifact_dir}/rvv/softmax_rvv.s"

{
  printf 'generated_at='; date --iso-8601=seconds
  printf 'x86_compiler='; "${x86_cxx}" --version | sed -n '1p'
  printf 'x86_flags='; print_flags "${common_flags[@]}" -mavx512f -mavx512dq -mavx512bw -mavx512vl -mfma
  printf 'rvv_compiler='; "${rvv_cxx}" --version | sed -n '1p'
  printf 'rvv_flags='; print_flags "${common_flags[@]}" -march=rv64gcv -mabi=lp64d
  printf 'rvv_target_vlen_bits=512\n'
  printf 'simulator_input=assembly_only\n'
  printf 'x86_source=%s\n' "${softmax_dir}/x86/softmax_avx512.cpp"
  printf 'rvv_source=%s\n' "${softmax_dir}/rvv/softmax_rvv.cpp"
} >"${artifact_dir}/x86/build_metadata.txt"
cp "${artifact_dir}/x86/build_metadata.txt" "${artifact_dir}/rvv/build_metadata.txt"

printf '%s\n' "Generated ${artifact_dir}/x86/softmax_avx512.s"
printf '%s\n' "Generated ${artifact_dir}/rvv/softmax_rvv.s"
