#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${script_dir}/common.sh"

require_file "${am_home}/Makefile.app"
require_executable "$(command -v "${rvv_toolchain_prefix}g++")"
require_executable "$(command -v "${rvv_toolchain_prefix}objdump")"
require_executable "$(command -v "${rvv_toolchain_prefix}nm")"

build_artifacts="${artifact_root}/build"
binary="${build_artifacts}/xsai-kernel-bench-riscv64-xs"
mkdir -p "${build_artifacts}" "${xsai_integration_dir}/build"

start_external_guard

make -C "${xsai_integration_dir}" clean \
  ARCH=riscv64-xs \
  TOOLCHAIN=GNU \
  LINUX_GNU_TOOLCHAIN=1 \
  AM_HOME="${am_home}" \
  MARCH=rv64gcv_zvl128b \
  MCMODEL=-mcmodel=medany \
  OBJDUMP="${script_dir}/gnu_objdump_compat.sh" \
  BINARY="${binary}" \
  DST_DIR="${xsai_integration_dir}/build/riscv64-xs/"
make -C "${xsai_integration_dir}" \
  ARCH=riscv64-xs \
  TOOLCHAIN=GNU \
  LINUX_GNU_TOOLCHAIN=1 \
  AM_HOME="${am_home}" \
  MARCH=rv64gcv_zvl128b \
  MCMODEL=-mcmodel=medany \
  OBJDUMP="${script_dir}/gnu_objdump_compat.sh" \
  BINARY="${binary}" \
  DST_DIR="${xsai_integration_dir}/build/riscv64-xs/"

python3 "${script_dir}/audit_disassembly.py" \
  --disassembly "${binary}.txt" \
  --output "${build_artifacts}/instruction_audit.json"
python3 "${script_dir}/check_l1_layout.py" \
  --elf "${binary}.elf" \
  --nm "$(command -v "${rvv_toolchain_prefix}nm")" \
  --output "${build_artifacts}/l1_layout.json"

write_external_versions "${build_artifacts}/build_metadata.txt"
{
  printf 'compiler='; "${rvv_toolchain_prefix}g++" --version | sed -n '1p'
  printf 'kernel_source_hash='
  find "${project_dir}/kernel" -path '*/rvv/*.cpp' -type f -print0 |
    sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}'
  printf 'harness_source_hash='
  find "${xsai_integration_dir}/src" -type f -print0 |
    sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}'
  printf 'binary_sha256=%s\n' "$(sha256sum "${binary}.bin" | awk '{print $1}')"
  printf 'elf_sha256=%s\n' "$(sha256sum "${binary}.elf" | awk '{print $1}')"
  printf 'disassembly_sha256=%s\n' \
    "$(sha256sum "${binary}.txt" | awk '{print $1}')"
  printf 'binary=%s\n' "${binary}.bin"
  printf 'elf=%s\n' "${binary}.elf"
  printf 'disassembly=%s\n' "${binary}.txt"
} >>"${build_artifacts}/build_metadata.txt"

finish_external_guard
printf 'Built XSAI bare-metal image: %s.bin\n' "${binary}"
