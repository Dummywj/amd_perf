#!/usr/bin/env bash
set -euo pipefail

gap_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../../scripts/common.sh
source "${gap_script_dir}/../../scripts/common.sh"

gap_artifact_root=${XSAI_VSET_GAP_ARTIFACT_ROOT:-"${artifact_root}/vset_gap"}
binary="${gap_artifact_root}/build/xsai-vset-gap-riscv64-xs.bin"
nemu=${NEMU:-"${nemu_home}/build/riscv64-nemu-interpreter"}
timeout_seconds=${NEMU_TIMEOUT_SECONDS:-300}
result_dir="${gap_artifact_root}/nemu"

require_file "${binary}"
require_executable "${nemu}"
mkdir -p "${result_dir}"
start_external_guard

set +e
timeout "${timeout_seconds}" "${nemu}" -b "${binary}" \
  2>&1 | tee "${result_dir}/nemu.log"
run_status=${PIPESTATUS[0]}
set -e
if [[ ${run_status} -ne 0 ]]; then
  printf 'NEMU exited with status %d. See %s\n' \
    "${run_status}" "${result_dir}/nemu.log" >&2
  exit "${run_status}"
fi

python3 "${gap_script_dir}/parse_results.py" \
  --log "${result_dir}/nemu.log" --source nemu --output-dir "${result_dir}"
write_external_versions "${result_dir}/run_metadata.txt"
{
  printf 'suite=vset_gap\n'
  printf 'log_sha256=%s\n' "$(sha256sum "${result_dir}/nemu.log" | awk '{print $1}')"
  printf 'summary_sha256=%s\n' "$(sha256sum "${result_dir}/summary.csv" | awk '{print $1}')"
} >>"${result_dir}/run_metadata.txt"
finish_external_guard
printf 'Standalone vset-gap NEMU functional validation passed.\n'
