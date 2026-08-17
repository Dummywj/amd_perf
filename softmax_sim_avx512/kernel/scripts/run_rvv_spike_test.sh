#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
kernel_dir=$(cd -- "${script_dir}/.." && pwd)
repo_dir=$(cd -- "${kernel_dir}/../.." && pwd)
build_dir=${BUILD_DIR:-"${kernel_dir}/build/rvv-spike"}
rvv_cxx=${RVV_CXX:-riscv64-linux-gnu-g++}
spike=${SPIKE:-"${repo_dir}/third_party/riscv-isa-sim/build/spike"}
proxy_kernel=${PK:-"${repo_dir}/third_party/riscv-pk/build/pk"}

kernels=(
  fma_throughput fma_latency axpy dot_product vector_copy vector_triad
  vector_reduction conversion vector_integer mixed_compute pointer_agu
)

if [[ ! -x "${spike}" || ! -x "${proxy_kernel}" ]]; then
  printf 'Spike or proxy kernel is missing.\n' >&2
  exit 2
fi

mkdir -p "${build_dir}"
common_flags=(-std=c++20 -Wall -Wextra -Wpedantic -fno-pie -I"${kernel_dir}" -mabi=lp64d)

"${rvv_cxx}" "${common_flags[@]}" -O2 -fno-tree-vectorize -march=rv64gc \
  -c "${kernel_dir}/reference/kernel_references.cpp" -o "${build_dir}/reference.o"
"${rvv_cxx}" "${common_flags[@]}" -O2 -fno-tree-vectorize -march=rv64gc \
  -c "${kernel_dir}/tests/kernel_rvv_correctness.cpp" -o "${build_dir}/test.o"

objects=("${build_dir}/reference.o" "${build_dir}/test.o")
for kernel in "${kernels[@]}"; do
  "${rvv_cxx}" "${common_flags[@]}" -O3 -march=rv64gcv \
    -c "${kernel_dir}/${kernel}/rvv/${kernel}_rvv.cpp" \
    -o "${build_dir}/${kernel}.o"
  objects+=("${build_dir}/${kernel}.o")
done

"${rvv_cxx}" -static -no-pie -march=rv64gcv -mabi=lp64d \
  "${objects[@]}" -o "${build_dir}/kernel_rvv_correctness"

for vlen in 128 512; do
  result="${build_dir}/spike_vlen${vlen}.txt"
  "${spike}" --isa="rv64gcv_zvl${vlen}b" \
    "${proxy_kernel}" "${build_dir}/kernel_rvv_correctness" >"${result}"
  pass_count=$(awk '$NF == "PASS" {count++} END {print count + 0}' "${result}")
  fail_count=$(awk '$NF == "FAIL" {count++} END {print count + 0}' "${result}")
  if [[ "${pass_count}" -ne 56 || "${fail_count}" -ne 0 ]]; then
    printf 'Unexpected Spike result for VLEN=%s: pass=%s fail=%s\n' \
      "${vlen}" "${pass_count}" "${fail_count}" >&2
    exit 1
  fi
  for kernel in "${kernels[@]}"; do
    artifact_dir="${kernel_dir}/${kernel}/artifacts/rvv"
    mkdir -p "${artifact_dir}"
    awk -v name="kernel=${kernel}" '$1 == name' "${result}" \
      >"${artifact_dir}/spike_vlen${vlen}.txt"
  done
done

for kernel in "${kernels[@]}"; do
  artifact_dir="${kernel_dir}/${kernel}/artifacts/rvv"
  {
    printf 'spike_commit=%s\n' "$(git -C "${repo_dir}/third_party/riscv-isa-sim" rev-parse HEAD)"
    printf 'proxy_kernel_commit=%s\n' "$(git -C "${repo_dir}/third_party/riscv-pk" rev-parse HEAD)"
    printf 'rvv_compiler=%s\n' "$("${rvv_cxx}" --version | sed -n '1p')"
    printf 'target_isa=rv64gcv\n'
    printf 'tested_vlen_bits=128,512\n'
    printf 'result=PASS\n'
  } >"${artifact_dir}/spike_validation_metadata.txt"
done

printf 'Spike correctness passed: 56/56 at VLEN=128 and VLEN=512.\n'
