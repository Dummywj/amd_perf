#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${script_dir}/common.sh"

load_xsai_environment
binary="${artifact_root}/build/xsai-kernel-bench-riscv64-xs.bin"
emulator=${XSAI_EMU:-"${noop_home}/build/emu"}
reference=${XSAI_DIFF_REF:-"${noop_home}/ready-to-run/riscv64-nemu-interpreter-so"}
timeout_seconds=${RTL_TIMEOUT_SECONDS:-14400}
max_cycles=${RTL_MAX_CYCLES:-500000000}
result_dir="${artifact_root}/rtl"

require_file "${binary}"
require_executable "${emulator}"
require_file "${reference}"
mkdir -p "${result_dir}"
start_external_guard

set +e
(
  cd "${noop_home}"
  timeout "${timeout_seconds}" "${emulator}" \
    -i "${binary}" \
    --diff "${reference}" \
    -C "${max_cycles}" \
    --force-dump-result
) 2>&1 | tee "${result_dir}/rtl.log"
run_status=${PIPESTATUS[0]}
set -e

if [[ ${run_status} -ne 0 ]]; then
  printf 'RTL run exited with status %d. See %s\n' \
    "${run_status}" "${result_dir}/rtl.log" >&2
  exit "${run_status}"
fi

python3 "${script_dir}/check_rtl_log.py" --log "${result_dir}/rtl.log"

python3 "${script_dir}/parse_results.py" \
  --log "${result_dir}/rtl.log" \
  --source rtl \
  --output-dir "${result_dir}"
write_external_versions "${result_dir}/run_metadata.txt"
{
  printf 'max_cycles=%s\n' "${max_cycles}"
  printf 'difftest_reference=%s\n' "${reference}"
} >>"${result_dir}/run_metadata.txt"
python3 "${script_dir}/refresh_run_metadata.py" \
  --metadata "${result_dir}/run_metadata.txt" \
  --result-dir "${result_dir}" \
  --build-dir "${artifact_root}/build"
finish_external_guard
printf 'RTL kernel measurements passed and were parsed.\n'
