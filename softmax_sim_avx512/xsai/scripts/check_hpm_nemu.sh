#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${script_dir}/common.sh"

smoke_dir="${xsai_integration_dir}/tests/hpm_smoke"
build_dir="${artifact_root}/hpm_smoke"
binary="${build_dir}/xsai-hpm-smoke-riscv64-xs"
nemu=${NEMU:-"${nemu_home}/build/riscv64-nemu-interpreter"}
mkdir -p "${build_dir}" "${smoke_dir}/build"

require_executable "$(command -v "${rvv_toolchain_prefix}g++")"
require_executable "${nemu}"
start_external_guard

make -C "${smoke_dir}" clean \
  ARCH=riscv64-xs TOOLCHAIN=GNU LINUX_GNU_TOOLCHAIN=1 \
  AM_HOME="${am_home}" MARCH=rv64gcv_zvl128b MCMODEL=-mcmodel=medany \
  OBJDUMP="${script_dir}/gnu_objdump_compat.sh" \
  BINARY="${binary}" DST_DIR="${smoke_dir}/build/riscv64-xs/"
make -C "${smoke_dir}" \
  ARCH=riscv64-xs TOOLCHAIN=GNU LINUX_GNU_TOOLCHAIN=1 \
  AM_HOME="${am_home}" MARCH=rv64gcv_zvl128b MCMODEL=-mcmodel=medany \
  OBJDUMP="${script_dir}/gnu_objdump_compat.sh" \
  BINARY="${binary}" DST_DIR="${smoke_dir}/build/riscv64-xs/"

timeout 60 "${nemu}" -b "${binary}.bin" 2>&1 | tee "${build_dir}/nemu.log"
rg -q 'XSAI_HPM_SMOKE status=PASS' "${build_dir}/nemu.log"
rg -q 'HIT GOOD TRAP' "${build_dir}/nemu.log"
finish_external_guard
printf 'XSAI HPM CSR smoke test passed under NEMU.\n'
