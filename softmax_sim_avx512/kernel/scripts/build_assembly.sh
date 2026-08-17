#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
kernel_dir=$(cd -- "${script_dir}/.." && pwd)
project_dir=$(cd -- "${kernel_dir}/.." && pwd)
x86_cxx=${X86_CXX:-c++}
rvv_cxx=${RVV_CXX:-riscv64-linux-gnu-g++}

kernels=(
  fma_throughput fma_latency axpy dot_product vector_copy vector_triad
  vector_reduction conversion vector_integer mixed_compute pointer_agu
)

common_flags=(
  -std=c++20 -O3 -Wall -Wextra -Wpedantic
  -fno-stack-protector -fno-asynchronous-unwind-tables
  -fno-unwind-tables -fno-exceptions -fno-rtti -fno-pie
  -fcf-protection=none -I"${kernel_dir}"
)
x86_flags=(-mavx512f -mavx512dq -mavx512bw -mavx512vl -mfma)
rvv_flags=(-march=rv64gcv -mabi=lp64d)

for kernel in "${kernels[@]}"; do
  artifact_dir="${kernel_dir}/${kernel}/artifacts"
  mkdir -p "${artifact_dir}/x86" "${artifact_dir}/rvv"
  "${x86_cxx}" "${common_flags[@]}" "${x86_flags[@]}" \
    -S "${kernel_dir}/${kernel}/x86/${kernel}_avx512.cpp" \
    -o "${artifact_dir}/x86/${kernel}_avx512.s"
  "${rvv_cxx}" "${common_flags[@]}" "${rvv_flags[@]}" \
    -S "${kernel_dir}/${kernel}/rvv/${kernel}_rvv.cpp" \
    -o "${artifact_dir}/rvv/${kernel}_rvv.s"

  {
    printf 'x86_compiler=%s\n' "$("${x86_cxx}" --version | sed -n '1p')"
    printf 'x86_flags=%s\n' "${common_flags[*]} ${x86_flags[*]}"
    printf 'rvv_compiler=%s\n' "$("${rvv_cxx}" --version | sed -n '1p')"
    printf 'rvv_flags=%s\n' "${common_flags[*]} ${rvv_flags[*]}"
    printf 'x86_source_sha256=%s\n' \
      "$(sha256sum "${kernel_dir}/${kernel}/x86/${kernel}_avx512.cpp" | cut -d' ' -f1)"
    printf 'rvv_source_sha256=%s\n' \
      "$(sha256sum "${kernel_dir}/${kernel}/rvv/${kernel}_rvv.cpp" | cut -d' ' -f1)"
    printf 'x86_assembly_sha256=%s\n' \
      "$(sha256sum "${artifact_dir}/x86/${kernel}_avx512.s" | cut -d' ' -f1)"
    printf 'rvv_assembly_sha256=%s\n' \
      "$(sha256sum "${artifact_dir}/rvv/${kernel}_rvv.s" | cut -d' ' -f1)"
    printf 'x86_recipe_sha256=%s\n' \
      "$(sha256sum "${project_dir}/recipes/x86.yaml" | cut -d' ' -f1)"
    printf 'rvv_recipe_sha256=%s\n' \
      "$(sha256sum "${project_dir}/recipes/rvv.yaml" | cut -d' ' -f1)"
    printf 'uop_catalog_sha256=%s\n' \
      "$(sha256sum "${project_dir}/uops/uop_kinds.yaml" | cut -d' ' -f1)"
    printf 'profile_sha256=%s\n' \
      "$(sha256sum "${project_dir}/profiles/amd_zen4.yaml" | cut -d' ' -f1)"
    printf 'simulator_input=assembly_only\n'
  } >"${artifact_dir}/build_metadata.txt"
done

printf 'Generated x86 and RVV assembly for %s kernels.\n' "${#kernels[@]}"
