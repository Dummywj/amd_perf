#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
softmax_dir=$(cd -- "${script_dir}/.." && pwd)
repo_dir=$(cd -- "${softmax_dir}/../../.." && pwd)
build_dir=${BUILD_DIR:-"${softmax_dir}/build"}
cpu=${CPU:-8}
numa_node=${NUMA_NODE:-0}
repetitions=${REPETITIONS:-7}
max_sibling_busy_percent=${MAX_SIBLING_BUSY_PERCENT:-5}
result_dir=${1:-"${softmax_dir}/artifacts/x86/cycles-$(date +%Y%m%d-%H%M%S)"}
smt_siblings=$(<"/sys/devices/system/cpu/cpu${cpu}/topology/thread_siblings_list")
sibling_cpu=$(tr ',' '\n' <<<"${smt_siblings}" | awk -v selected="${cpu}" '$1 != selected { print; exit }')

cpu_ticks() {
  awk -v cpu_name="cpu${1}" '$1 == cpu_name {
    total = 0
    for (field = 2; field <= NF; ++field) total += $field
    print total, $5 + $6
  }' /proc/stat
}

mkdir -p "${result_dir}"
cmake -S "${softmax_dir}" -B "${build_dir}" -DCMAKE_BUILD_TYPE=Release
cmake --build "${build_dir}" --target softmax_cycles -j "${JOBS:-16}"

{
  date --iso-8601=seconds
  hostname
  uname -a
  lscpu
  lscpu -e=CPU,NODE,SOCKET,CORE,ONLINE
  printf 'selected_cpu=%s\n' "${cpu}"
  printf 'selected_numa_node=%s\n' "${numa_node}"
  printf 'smt_siblings=%s\n' "${smt_siblings}"
  printf 'perf_event_paranoid=' && cat /proc/sys/kernel/perf_event_paranoid
  c++ --version
  cmake --version
  git -C "${repo_dir}" rev-parse HEAD
  sha256sum "${softmax_dir}/x86/softmax_avx512.cpp"
  sha256sum "${softmax_dir}/benchmarks/softmax_cycles.cpp"
  sha256sum "${softmax_dir}/CMakeLists.txt"
  sha256sum "${softmax_dir}/artifacts/x86/softmax_avx512.s"
  sha256sum "${build_dir}/libsoftmax_avx512.a"
  sha256sum "${build_dir}/softmax_cycles"
  sha256sum "${softmax_dir}/../../profiles/amd_zen4.yaml"
} >"${result_dir}/environment.txt"

objdump -d --no-show-raw-insn --demangle "${build_dir}/softmax_cycles" \
  >"${result_dir}/disassembly.txt"

read -r sibling_total_before sibling_idle_before < <(cpu_ticks "${sibling_cpu}")
numactl --physcpubind="${cpu}" --membind="${numa_node}" \
  "${build_dir}/softmax_cycles" "${repetitions}" >"${result_dir}/raw.json"
read -r sibling_total_after sibling_idle_after < <(cpu_ticks "${sibling_cpu}")
sibling_busy_percent=$(awk \
  -v total_before="${sibling_total_before}" -v idle_before="${sibling_idle_before}" \
  -v total_after="${sibling_total_after}" -v idle_after="${sibling_idle_after}" \
  'BEGIN {
    total = total_after - total_before
    idle = idle_after - idle_before
    printf "%.3f", (total > 0 ? 100.0 * (total - idle) / total : 0.0)
  }')
printf 'smt_sibling_cpu=%s\n' "${sibling_cpu}" >>"${result_dir}/environment.txt"
printf 'smt_sibling_busy_percent=%s\n' "${sibling_busy_percent}" \
  >>"${result_dir}/environment.txt"
if awk -v busy="${sibling_busy_percent}" -v maximum="${max_sibling_busy_percent}" \
  'BEGIN { exit !(busy > maximum) }'; then
  printf 'SMT sibling CPU %s was %.3f%% busy (limit %.3f%%)\n' \
    "${sibling_cpu}" "${sibling_busy_percent}" "${max_sibling_busy_percent}" >&2
  exit 2
fi

"${script_dir}/summarize_cycles.py" "${result_dir}/raw.json" \
  "${result_dir}/summary.json" "${result_dir}/summary.md"
printf 'Results: %s\n' "${result_dir}"
