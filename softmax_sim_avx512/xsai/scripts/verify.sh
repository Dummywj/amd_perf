#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
xsai_dir=$(cd -- "${script_dir}/.." && pwd)

python3 -m unittest discover -s "${xsai_dir}/tests" -p 'test_*.py'
"${script_dir}/build_baremetal.sh"
"${script_dir}/run_nemu.sh"
