#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(cd -- "${script_dir}/.." && pwd)
repo_dir=$(cd -- "${project_dir}/.." && pwd)
build_dir=${BUILD_DIR:-"${project_dir}/build"}
cpu=${CPU:-8}
numa_node=${NUMA_NODE:-0}
repetitions=${REPETITIONS:-7}
result_dir=${1:-"${project_dir}/results/run-$(date +%Y%m%d-%H%M%S)"}

mkdir -p "${result_dir}"

cmake -S "${project_dir}" -B "${build_dir}" -DCMAKE_BUILD_TYPE=Release
cmake --build "${build_dir}" -j "${JOBS:-16}"

binary="${build_dir}/amd_profile_benchmark"

{
  date --iso-8601=seconds
  hostname
  uname -a
  lscpu
  lscpu -e=CPU,NODE,SOCKET,CORE,ONLINE
  printf 'perf_event_paranoid=' && cat /proc/sys/kernel/perf_event_paranoid
  printf 'nmi_watchdog=' && cat /proc/sys/kernel/nmi_watchdog
  perf --version
  c++ --version
  cmake --version
  git -C "${repo_dir}" rev-parse HEAD
  git -C "${repo_dir}" status --short
  git -C "${repo_dir}/third_party/google-benchmark" describe --tags --always
} >"${result_dir}/environment.txt"

objdump -d --no-show-raw-insn --demangle "${binary}" \
  >"${result_dir}/disassembly.txt"

numactl --physcpubind="${cpu}" --membind="${numa_node}" \
  "${binary}" \
  --benchmark_repetitions="${repetitions}" \
  --benchmark_report_aggregates_only=false \
  --benchmark_out="${result_dir}/raw.json" \
  --benchmark_out_format=json

python3 "${script_dir}/summarize.py" \
  "${result_dir}/raw.json" "${result_dir}/summary.md"

printf '%s\n' "Results: ${result_dir}"
