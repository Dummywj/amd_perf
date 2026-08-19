#!/usr/bin/env bash
set -euo pipefail

gap_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
gap_dir=$(cd -- "${gap_script_dir}/.." && pwd)
# shellcheck source=../../scripts/common.sh
source "${gap_script_dir}/../../scripts/common.sh"

require_file "${am_home}/Makefile.app"
require_executable "$(command -v "${rvv_toolchain_prefix}g++")"
require_executable "$(command -v "${rvv_toolchain_prefix}objdump")"
require_executable "$(command -v "${rvv_toolchain_prefix}nm")"

gap_artifact_root=${XSAI_VSET_GAP_ARTIFACT_ROOT:-"${artifact_root}/vset_gap"}
build_dir="${gap_artifact_root}/build"
binary="${build_dir}/xsai-vset-gap-riscv64-xs"
mkdir -p "${build_dir}" "${gap_dir}/build"

start_external_guard
make -C "${gap_dir}" clean \
  ARCH=riscv64-xs TOOLCHAIN=GNU LINUX_GNU_TOOLCHAIN=1 \
  AM_HOME="${am_home}" MARCH=rv64gcv_zvl128b MCMODEL=-mcmodel=medany \
  OBJDUMP="${script_dir}/gnu_objdump_compat.sh" BINARY="${binary}" \
  DST_DIR="${gap_dir}/build/riscv64-xs/"
make -C "${gap_dir}" \
  ARCH=riscv64-xs TOOLCHAIN=GNU LINUX_GNU_TOOLCHAIN=1 \
  AM_HOME="${am_home}" MARCH=rv64gcv_zvl128b MCMODEL=-mcmodel=medany \
  OBJDUMP="${script_dir}/gnu_objdump_compat.sh" BINARY="${binary}" \
  DST_DIR="${gap_dir}/build/riscv64-xs/"

python3 "${gap_script_dir}/audit_disassembly.py" \
  --disassembly "${binary}.txt" \
  --output "${build_dir}/instruction_audit.json"
python3 "${gap_script_dir}/check_l1_layout.py" \
  --elf "${binary}.elf" \
  --nm "$(command -v "${rvv_toolchain_prefix}nm")" \
  --output "${build_dir}/l1_layout.json"

write_external_versions "${build_dir}/build_metadata.txt"
{
  printf 'suite=vset_gap\n'
  printf 'iterations=%s\n' "${ITERATIONS:-64}"
  printf 'samples=%s\n' "${SAMPLES:-5}"
  printf 'source_hash='
  find "${gap_dir}/src" -type f -print0 | sort -z | \
    xargs -0 sha256sum | sha256sum | awk '{print $1}'
  printf 'binary_sha256=%s\n' "$(sha256sum "${binary}.bin" | awk '{print $1}')"
  printf 'elf_sha256=%s\n' "$(sha256sum "${binary}.elf" | awk '{print $1}')"
  printf 'disassembly_sha256=%s\n' \
    "$(sha256sum "${binary}.txt" | awk '{print $1}')"
  printf 'binary=%s\n' "${binary}.bin"
  printf 'elf=%s\n' "${binary}.elf"
  printf 'disassembly=%s\n' "${binary}.txt"
} >>"${build_dir}/build_metadata.txt"
finish_external_guard
printf 'Built standalone XSAI vset-gap image: %s.bin\n' "${binary}"
