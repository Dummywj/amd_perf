#!/usr/bin/env bash
set -euo pipefail

gap_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../../scripts/common.sh
source "${gap_script_dir}/../../scripts/common.sh"

load_xsai_environment
gap_artifact_root=${XSAI_VSET_GAP_ARTIFACT_ROOT:-"${artifact_root}/vset_gap"}
build_dir="${gap_artifact_root}/build"
binary="${build_dir}/xsai-vset-gap-riscv64-xs.bin"
elf="${build_dir}/xsai-vset-gap-riscv64-xs.elf"
disassembly="${build_dir}/xsai-vset-gap-riscv64-xs.txt"
instruction_audit="${build_dir}/instruction_audit.json"
l1_layout="${build_dir}/l1_layout.json"
build_metadata="${build_dir}/build_metadata.txt"
emulator=${XSAI_EMU:-"${noop_home}/build/emu"}
reference=${XSAI_DIFF_REF:-"${noop_home}/ready-to-run/riscv64-nemu-interpreter-so"}
timeout_seconds=${RTL_TIMEOUT_SECONDS:-3600}
max_cycles=${RTL_MAX_CYCLES:-100000000}
result_dir="${gap_artifact_root}/rtl"

require_file "${binary}"
require_file "${elf}"
require_file "${disassembly}"
require_file "${instruction_audit}"
require_file "${l1_layout}"
require_file "${build_metadata}"
require_executable "${emulator}"
require_file "${reference}"
mkdir -p "${result_dir}"
start_external_guard

set +e
(
  cd "${noop_home}"
  timeout "${timeout_seconds}" "${emulator}" \
    -i "${binary}" --diff "${reference}" -C "${max_cycles}" \
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
python3 "${gap_script_dir}/parse_results.py" \
  --log "${result_dir}/rtl.log" --source rtl --output-dir "${result_dir}"
write_external_versions "${result_dir}/run_metadata.txt"
{
  printf 'suite=vset_gap\n'
  printf 'max_cycles=%s\n' "${max_cycles}"
  printf 'difftest_reference=%s\n' "${reference}"
  printf 'log_sha256=%s\n' "$(sha256sum "${result_dir}/rtl.log" | awk '{print $1}')"
  printf 'summary_sha256=%s\n' "$(sha256sum "${result_dir}/summary.csv" | awk '{print $1}')"
  printf 'samples_sha256=%s\n' "$(sha256sum "${result_dir}/samples.csv" | awk '{print $1}')"
  printf 'result_metadata_sha256=%s\n' \
    "$(sha256sum "${result_dir}/result_metadata.json" | awk '{print $1}')"
  printf 'build_metadata_sha256=%s\n' \
    "$(sha256sum "${build_metadata}" | awk '{print $1}')"
  printf 'binary_sha256=%s\n' "$(sha256sum "${binary}" | awk '{print $1}')"
  printf 'elf_sha256=%s\n' "$(sha256sum "${elf}" | awk '{print $1}')"
  printf 'disassembly_sha256=%s\n' \
    "$(sha256sum "${disassembly}" | awk '{print $1}')"
  printf 'instruction_audit_sha256=%s\n' \
    "$(sha256sum "${instruction_audit}" | awk '{print $1}')"
  printf 'l1_layout_sha256=%s\n' \
    "$(sha256sum "${l1_layout}" | awk '{print $1}')"
} >>"${result_dir}/run_metadata.txt"
finish_external_guard
printf 'Standalone vset-gap RTL measurements passed and were parsed.\n'
