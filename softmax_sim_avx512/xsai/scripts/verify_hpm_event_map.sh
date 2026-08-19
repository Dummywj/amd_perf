#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${script_dir}/common.sh"

rtl_dir=${XSAI_RTL_DIR:-"${noop_home}/build/rtl"}
output=${XSAI_HPM_MAP_OUTPUT:-"${artifact_root}/build/hpm_event_map.json"}

start_external_guard
python3 "${script_dir}/verify_hpm_event_map.py" \
  --xsai-root "${noop_home}" \
  --rtl-dir "${rtl_dir}" \
  --output "${output}"
finish_external_guard
