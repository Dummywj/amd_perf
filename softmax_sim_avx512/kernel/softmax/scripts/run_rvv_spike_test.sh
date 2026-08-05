#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
softmax_dir=$(cd -- "${script_dir}/.." && pwd)
repo_dir=$(cd -- "${softmax_dir}/../../.." && pwd)
build_dir="${softmax_dir}/build/rvv-spike"
artifact_dir="${softmax_dir}/artifacts/rvv"
rvv_cxx=${RVV_CXX:-riscv64-linux-gnu-g++}
spike=${SPIKE:-"${repo_dir}/third_party/riscv-isa-sim/build/spike"}
proxy_kernel=${PK:-"${repo_dir}/third_party/riscv-pk/build/pk"}

if [[ ! -x "${spike}" || ! -x "${proxy_kernel}" ]]; then
  printf '%s\n' >&2 \
    "Spike or proxy kernel is missing. Build them first with:" \
    "  ${script_dir}/build_riscv_tools.sh"
  exit 2
fi

mkdir -p "${build_dir}" "${artifact_dir}"

common_flags=(
  -std=c++20 -Wall -Wextra -Wpedantic -fno-pie
  -I"${softmax_dir}" -mabi=lp64d
)

"${rvv_cxx}" "${common_flags[@]}" -O2 -fno-tree-vectorize -march=rv64gc \
  -c "${softmax_dir}/reference/softmax_reference.cpp" \
  -o "${build_dir}/softmax_reference.o"

"${rvv_cxx}" "${common_flags[@]}" -O3 -march=rv64gcv \
  -c "${softmax_dir}/rvv/softmax_rvv.cpp" \
  -o "${build_dir}/softmax_rvv.o"

"${rvv_cxx}" "${common_flags[@]}" -O2 -fno-tree-vectorize -march=rv64gc \
  -c "${softmax_dir}/tests/softmax_rvv_correctness.cpp" \
  -o "${build_dir}/softmax_rvv_correctness.o"

"${rvv_cxx}" -static -no-pie -march=rv64gcv -mabi=lp64d \
  "${build_dir}/softmax_reference.o" \
  "${build_dir}/softmax_rvv.o" \
  "${build_dir}/softmax_rvv_correctness.o" \
  -o "${build_dir}/softmax_rvv_correctness"

for vlen in 128 512; do
  printf '\nRunning RVV correctness with VLEN=%s\n' "${vlen}"
  "${spike}" --isa="rv64gcv_zvl${vlen}b" \
    "${proxy_kernel}" "${build_dir}/softmax_rvv_correctness" \
    2>&1 | tee "${artifact_dir}/spike_vlen${vlen}.txt"
done

for result_file in "${artifact_dir}/spike_vlen128.txt" \
                   "${artifact_dir}/spike_vlen512.txt"; do
  pass_count=$(awk '$NF == "PASS" {count++} END {print count + 0}' "${result_file}")
  if [[ "${pass_count}" -ne 36 ]] || grep -q 'FAIL' "${result_file}"; then
    printf 'Unexpected Spike result in %s: %s PASS lines\n' \
      "${result_file}" "${pass_count}" >&2
    exit 1
  fi
done

{
  printf 'generated_at='; date --iso-8601=seconds
  printf 'spike_commit='; git -C "${repo_dir}/third_party/riscv-isa-sim" rev-parse HEAD
  printf 'spike_version='; "${spike}" --help 2>&1 | sed -n '1p'
  printf 'proxy_kernel_commit='; git -C "${repo_dir}/third_party/riscv-pk" rev-parse HEAD
  printf 'rvv_compiler='; "${rvv_cxx}" --version | sed -n '1p'
  printf 'target_isa=rv64gcv\n'
  printf 'target_abi=lp64d\n'
  printf 'tested_vlen_bits=128,512\n'
  printf 'result=PASS\n'
} >"${artifact_dir}/spike_validation_metadata.txt"
