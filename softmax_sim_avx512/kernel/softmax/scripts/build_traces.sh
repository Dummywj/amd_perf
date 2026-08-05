#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
softmax_dir=$(cd -- "${script_dir}/.." && pwd)
sim_dir=$(cd -- "${softmax_dir}/../.." && pwd)
python_bin=${PYTHON:-python3}

if ! "${python_bin}" -c 'import yaml' >/dev/null 2>&1; then
  cat >&2 <<'EOF'
build_traces.sh: PyYAML is required by the assembly parser.
Set PYTHON to an interpreter that provides PyYAML, for example:
  PYTHON=/path/to/python ./build_traces.sh
EOF
  exit 2
fi

"${script_dir}/build_assembly.sh"

cd "${sim_dir}"
artifact_dir="kernel/softmax/artifacts"

parser="${sim_dir}/utils/asm_to_uop.py"
binder="${sim_dir}/utils/bind_uop_profile.py"
catalog="uops/uop_kinds.yaml"

"${python_bin}" "${parser}" \
  --isa x86 \
  --assembly "${artifact_dir}/x86/softmax_avx512.s" \
  --function softmax_avx512_f32 \
  --recipe "recipes/x86.yaml" \
  --catalog "${catalog}" \
  --output "${artifact_dir}/x86/softmax_uops.json"

"${python_bin}" "${parser}" \
  --isa rvv \
  --assembly "${artifact_dir}/rvv/softmax_rvv.s" \
  --function softmax_rvv_f32 \
  --recipe "recipes/rvv.yaml" \
  --catalog "${catalog}" \
  --output "${artifact_dir}/rvv/softmax_uops.json"

"${python_bin}" "${binder}" \
  --trace "${artifact_dir}/x86/softmax_uops.json" \
  --profile "profiles/amd_zen4.yaml" \
  --output "${artifact_dir}/x86/softmax_uops_bound.json"

printf '%s\n' "Generated generic traces under ${artifact_dir}" \
  "Bound x86 trace to ${sim_dir}/profiles/amd_zen4.yaml"
