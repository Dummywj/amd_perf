#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 && $# -ne 4 ]]; then
  echo "usage: collect_ops_environment.sh <output.md> <cpu> <smt-sibling> [dense-exploratory]" >&2
  exit 2
fi

output=$1
cpu=$2
sibling=$3
mode=${4:-formal}
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

exec >"$output"

if [[ "$mode" == "dense-exploratory" ]]; then
  echo "# EXPLORATORY / NON-FORMAL - Dense FP32 environment"
  echo
  echo "**This newly collected dense run may be affected by external Java/ZGC activity and CPU contention.**"
  echo
  echo "**Relative trends only. Do not use for absolute performance, cross-machine comparisons, performance regression, capacity planning, hardware limits, or formal acceptance.**"
  echo
elif [[ "$mode" != "formal" ]]; then
  echo "unknown mode: $mode" >&2
  exit 2
else
  echo "# FP32 operations environment"
  echo
fi
echo
echo "- Selected CPU: \`$cpu\`"
echo "- SMT sibling: \`$sibling\`"
echo "- NUMA policy: \`--physcpubind=$cpu --membind=0\`"
echo

section() {
  echo "## $1"
  echo
  echo '```text'
}

end_section() {
  echo '```'
  echo
}

section "Identity and kernel"
date --iso-8601=seconds
hostname
uname -a
end_section

section "CPU topology and caches"
lscpu
lscpu -e=CPU,NODE,SOCKET,CORE,ONLINE,MAXMHZ,MINMHZ
end_section

section "Selected core"
lscpu -e=CPU,NODE,SOCKET,CORE,ONLINE | awk -v cpu="$cpu" -v sibling="$sibling" \
  'NR == 1 || $1 == cpu || $1 == sibling'
end_section

section "NUMA"
numactl --hardware
end_section

section "Memory, swap, and filesystem"
free -h
swapon --show
awk '$1 == "pswpin" || $1 == "pswpout" {print}' /proc/vmstat
df -h "$root" /tmp
end_section

section "Frequency policy"
for path in \
  "/sys/devices/system/cpu/cpu${cpu}/cpufreq/scaling_governor" \
  "/sys/devices/system/cpu/cpu${cpu}/cpufreq/scaling_driver" \
  "/sys/devices/system/cpu/cpu${cpu}/cpufreq/scaling_min_freq" \
  "/sys/devices/system/cpu/cpu${cpu}/cpufreq/scaling_max_freq" \
  "/sys/devices/system/cpu/cpu${cpu}/cpufreq/scaling_cur_freq" \
  "/sys/devices/system/cpu/cpufreq/boost"; do
  if [[ -r "$path" ]]; then
    printf '%s: ' "$path"
    cat "$path"
  else
    echo "$path: unavailable"
  fi
done
end_section

section "Microcode"
awk -F: '/^(processor|microcode)/ {print $1 ":" $2; if ($1 ~ /microcode/) exit}' /proc/cpuinfo
end_section

section "Toolchain"
c++ --version
cmake --version
perf --version
numactl --version
python3 --version
end_section

section "Git"
git -C "$root" rev-parse HEAD
git -C "$root" status --short --branch
git -C "$root" submodule status
end_section

section "Dependency revisions"
git -C "$root/third_party/google-benchmark" describe --always --dirty
git -C "$root/third_party/sleef" describe --always --dirty
git -C "$root/third_party/sleef/submodules/tlfloat" describe --always --dirty
end_section

section "Build flags"
awk '/ops_common.cpp/ {print; exit}' "$root/gbench-test/build-ops-release/compile_commands.json"
end_section

section "Selected CPU and sibling resident tasks"
ps -eLo psr=,pid=,tid=,comm= | awk -v cpu="$cpu" -v sibling="$sibling" \
  '$1 == cpu || $1 == sibling'
end_section
