#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${script_dir}/common.sh"

load_xsai_environment
require_file "${noop_home}/Makefile"
jobs=${RTL_BUILD_JOBS:-8}
threads=${RTL_EMU_THREADS:-8}
result_dir="${artifact_root}/rtl-build"
mkdir -p "${result_dir}"
start_external_guard

printf '%s\n' \
  'Starting the long XSAI Verilator build.' \
  'Configuration: DefaultMatrixConfig, one core, CUTE instantiated, no trace.'

make -C "${noop_home}" emu \
  -j"${jobs}" \
  CONFIG=DefaultMatrixConfig \
  NUM_CORES=1 \
  WITH_DRAMSIM3=1 \
  WITH_CHISELDB=1 \
  WITH_CONSTANTIN=0 \
  EMU_THREADS="${threads}" \
  2>&1 | tee "${result_dir}/build.log"

require_executable "${noop_home}/build/emu"
write_external_versions "${result_dir}/build_metadata.txt"
{
  printf 'emu_threads=%s\n' "${threads}"
  printf 'with_dramsim3=1\n'
  printf 'with_chiseldb=1\n'
  printf 'with_constantin=0\n'
  printf 'emu_trace=disabled\n'
} >>"${result_dir}/build_metadata.txt"
finish_external_guard
printf 'Built RTL emulator: %s\n' "${noop_home}/build/emu"
