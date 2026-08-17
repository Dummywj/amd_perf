#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
kernel_dir=$(cd -- "${script_dir}/.." && pwd)
project_dir=$(cd -- "${kernel_dir}/.." && pwd)
repo_dir=$(cd -- "${project_dir}/.." && pwd)
build_dir=${BUILD_DIR:-"${kernel_dir}/build"}
cpu=${CPU:-8}
numa_node=${NUMA_NODE:-0}
repetitions=${REPETITIONS:-7}
selected=${KERNEL:-all}
result_dir=${1:-"${project_dir}/artifacts/kernel_validation/hardware"}

mkdir -p "${result_dir}"
cmake -S "${kernel_dir}" -B "${build_dir}" -DCMAKE_BUILD_TYPE=Release
cmake --build "${build_dir}" --target kernel_cycles -j "${JOBS:-16}"

{
  date --iso-8601=seconds
  hostname
  uname -a
  lscpu
  printf 'selected_cpu=%s\n' "${cpu}"
  printf 'selected_numa_node=%s\n' "${numa_node}"
  printf 'repetitions=%s\n' "${repetitions}"
  printf 'selected_kernel=%s\n' "${selected}"
  printf 'perf_event_paranoid=' && cat /proc/sys/kernel/perf_event_paranoid
  c++ --version
  cmake --version
  git -C "${repo_dir}" rev-parse HEAD
  sha256sum "${kernel_dir}/benchmarks/kernel_cycles.cpp"
  sha256sum "${kernel_dir}/CMakeLists.txt"
  sha256sum "${project_dir}/profiles/amd_zen4.yaml"
} >"${result_dir}/environment.txt"

numactl --physcpubind="${cpu}" --membind="${numa_node}" \
  "${build_dir}/kernel_cycles" "${selected}" "${repetitions}" \
  >"${result_dir}/raw.json"

printf 'Hardware measurements: %s\n' "${result_dir}"
