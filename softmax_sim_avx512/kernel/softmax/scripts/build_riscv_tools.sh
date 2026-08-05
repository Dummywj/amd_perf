#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "${script_dir}/../../../../" && pwd)
spike_dir="${repo_dir}/third_party/riscv-isa-sim"
pk_dir="${repo_dir}/third_party/riscv-pk"
jobs=${JOBS:-16}

if [[ ! -x "${spike_dir}/configure" || ! -x "${pk_dir}/configure" ]]; then
  printf '%s\n' >&2 \
    "RISC-V submodules are missing. Run:" \
    "  git submodule update --init --recursive third_party/riscv-isa-sim third_party/riscv-pk"
  exit 2
fi

mkdir -p "${spike_dir}/build" "${pk_dir}/build"

(
  cd "${spike_dir}/build"
  ../configure --prefix="${PWD}/install"
  make -j"${jobs}" spike
)

(
  cd "${pk_dir}/build"
  LDFLAGS=-Wl,--no-warn-mismatch ../configure \
    --prefix="${PWD}/install" \
    --host=riscv64-linux-gnu \
    --with-arch=rv64gcv_zicsr_zifencei \
    --with-abi=lp64d
  # GNU binutils marks pk's assembly-only entry object as soft-float even
  # though it does not pass FP arguments. The scoped linker flag above allows
  # that object to link with the lp64d C objects provided by this toolchain.
  make -j"${jobs}" pk
  make install
)

printf '%s\n' \
  "Spike: ${spike_dir}/build/spike" \
  "Proxy kernel: ${pk_dir}/build/pk"
