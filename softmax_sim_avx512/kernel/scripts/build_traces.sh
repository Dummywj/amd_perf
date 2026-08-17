#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
kernel_dir=$(cd -- "${script_dir}/.." && pwd)
project_dir=$(cd -- "${kernel_dir}/.." && pwd)
python_bin=${PYTHON:-python3}

kernels=(
  fma_throughput fma_latency axpy dot_product vector_copy vector_triad
  vector_reduction conversion vector_integer mixed_compute pointer_agu
)

"${script_dir}/build_assembly.sh"

cd "${project_dir}"
for kernel in "${kernels[@]}"; do
  artifact_dir="kernel/${kernel}/artifacts"
  "${python_bin}" "src/utils/asm_to_uop.py" \
    --isa x86 \
    --assembly "${artifact_dir}/x86/${kernel}_avx512.s" \
    --function "${kernel}_avx512_f32" \
    --recipe "recipes/x86.yaml" \
    --catalog "uops/uop_kinds.yaml" \
    --output "${artifact_dir}/x86/${kernel}_uops.json"

  "${python_bin}" "src/utils/asm_to_uop.py" \
    --isa rvv \
    --assembly "${artifact_dir}/rvv/${kernel}_rvv.s" \
    --function "${kernel}_rvv_f32" \
    --recipe "recipes/rvv.yaml" \
    --catalog "uops/uop_kinds.yaml" \
    --output "${artifact_dir}/rvv/${kernel}_uops.json"

  "${python_bin}" "src/utils/bind_uop_profile.py" \
    --trace "${artifact_dir}/x86/${kernel}_uops.json" \
    --profile "profiles/amd_zen4.yaml" \
    --output "${artifact_dir}/x86/${kernel}_uops_bound.json"
done

printf 'Generated static semantic traces for %s kernels.\n' "${#kernels[@]}"
