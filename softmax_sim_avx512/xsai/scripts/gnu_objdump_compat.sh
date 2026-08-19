#!/usr/bin/env bash
set -euo pipefail

# nexus-am's riscv64-xs image rule passes an LLVM-only option. Keep the
# compatibility adapter in this repository and leave nexus-am untouched.
toolchain_prefix=${RVV_TOOLCHAIN_PREFIX:-riscv64-linux-gnu-}
arguments=()
for argument in "$@"; do
  case "${argument}" in
    --triple=riscv64) ;;
    *) arguments+=("${argument}") ;;
  esac
done
exec "${toolchain_prefix}objdump" "${arguments[@]}"
