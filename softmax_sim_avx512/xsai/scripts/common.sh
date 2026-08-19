#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
xsai_integration_dir=$(cd -- "${script_dir}/.." && pwd)
project_dir=$(cd -- "${xsai_integration_dir}/.." && pwd)
workspace_dir=$(cd -- "${project_dir}/.." && pwd)

xsai_env_root=${XSAI_ENV_ROOT:-"${HOME}/project/xsai-env"}
am_home=${AM_HOME:-"${xsai_env_root}/nexus-am"}
noop_home=${NOOP_HOME:-"${xsai_env_root}/XSAI"}
nemu_home=${NEMU_HOME:-"${xsai_env_root}/NEMU"}
rvv_toolchain_prefix=${RVV_TOOLCHAIN_PREFIX:-riscv64-linux-gnu-}
artifact_root=${XSAI_ARTIFACT_ROOT:-"${project_dir}/artifacts/xsai"}

load_xsai_environment() {
  local environment_script="${xsai_env_root}/env.sh"
  require_file "${environment_script}"
  XSAI_ENV_QUIET=1 source "${environment_script}"
  am_home=${AM_HOME:-"${am_home}"}
  noop_home=${NOOP_HOME:-"${noop_home}"}
  nemu_home=${NEMU_HOME:-"${nemu_home}"}
}

require_file() {
  if [[ ! -e "$1" ]]; then
    printf 'Missing required path: %s\n' "$1" >&2
    exit 2
  fi
}

require_executable() {
  if [[ ! -x "$1" ]]; then
    printf 'Missing executable: %s\n' "$1" >&2
    exit 2
  fi
}

snapshot_external_trees() {
  nexus_status_before=$(git -C "${am_home}" status --porcelain=v1 --untracked-files=all)
  xsai_status_before=$(git -C "${noop_home}" status --porcelain=v1 --untracked-files=all)
  nemu_status_before=$(git -C "${nemu_home}" status --porcelain=v1 --untracked-files=all)
}

start_external_guard() {
  snapshot_external_trees
  trap 'assert_external_trees_unchanged' EXIT
}

finish_external_guard() {
  assert_external_trees_unchanged
  trap - EXIT
}

assert_external_trees_unchanged() {
  local nexus_status_after xsai_status_after nemu_status_after
  nexus_status_after=$(git -C "${am_home}" status --porcelain=v1 --untracked-files=all)
  xsai_status_after=$(git -C "${noop_home}" status --porcelain=v1 --untracked-files=all)
  nemu_status_after=$(git -C "${nemu_home}" status --porcelain=v1 --untracked-files=all)

  if [[ "${nexus_status_before}" != "${nexus_status_after}" ||
        "${xsai_status_before}" != "${xsai_status_after}" ||
        "${nemu_status_before}" != "${nemu_status_after}" ]]; then
    printf 'A tracked or untracked external source-tree file changed.\n' >&2
    printf '%s\n' 'Only ignored build outputs are allowed under xsai-env.' >&2
    return 1
  fi
}

write_external_versions() {
  local output=$1
  {
    printf 'workspace_commit=%s\n' "$(git -C "${workspace_dir}" rev-parse HEAD)"
    printf 'xsai_commit=%s\n' "$(git -C "${noop_home}" rev-parse HEAD)"
    printf 'nexus_am_commit=%s\n' "$(git -C "${am_home}" rev-parse HEAD)"
    printf 'nemu_commit=%s\n' "$(git -C "${nemu_home}" rev-parse HEAD)"
    printf 'xsai_config=DefaultMatrixConfig\n'
    printf 'num_cores=1\n'
    printf 'target_isa=rv64gcv_zvl128b\n'
    printf 'vlen_bits=128\n'
    printf 'cute_instantiated=true\n'
    printf 'cute_instructions=false\n'
  } >"${output}"
}
