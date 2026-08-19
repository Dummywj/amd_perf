#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${script_dir}/common.sh"

binary="${artifact_root}/build/xsai-kernel-bench-riscv64-xs.bin"
nemu=${NEMU:-"${nemu_home}/build/riscv64-nemu-interpreter"}
timeout_seconds=${NEMU_TIMEOUT_SECONDS:-300}
result_dir="${artifact_root}/nemu"

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

python3 "${script_dir}/parse_results.py" \
  --log "${result_dir}/nemu.log" \
  --source nemu \
  --output-dir "${result_dir}"
write_external_versions "${result_dir}/run_metadata.txt"
finish_external_guard
printf 'NEMU functional validation passed.\n'
