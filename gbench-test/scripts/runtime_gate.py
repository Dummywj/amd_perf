#!/usr/bin/env python3

import argparse
import csv
import json
import os
import re
import resource
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


MIB = 1024 * 1024
GIB = 1024 * 1024 * 1024
CPU = 8
SMT_SIBLING = 200

WARM_FILTERS = {
    "reduce": r"reduce/sum/avx512/1024/1024$",
    "gather": r"gather/sequential/avx512/1024/1024$",
    "scatter": r"scatter/sequential/avx512/1024/1024$",
    "softmax": r"softmax/avx512/1024/1024$",
}

SMOKE_FILTERS = {
    "reduce": r"reduce/sum/avx512/67108864/67108864$",
    "gather": r"gather/sequential/avx512/67108864/67108864$",
    "scatter": r"scatter/sequential/avx512/67108864/67108864$",
    "softmax": r"softmax/avx512/67108864/67108864$",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run one approved benchmark binary under the runtime gates"
    )
    parser.add_argument("label", choices=sorted(WARM_FILTERS))
    parser.add_argument("binary")
    parser.add_argument("result_json")
    parser.add_argument("runtime_dir")
    parser.add_argument(
        "--smoke", action="store_true", help="run one 64M case once to validate gate tooling"
    )
    return parser.parse_args()


def read_key_values(path):
    values = {}
    with open(path, encoding="utf-8") as source:
        for line in source:
            parts = line.split()
            if len(parts) >= 2:
                values[parts[0].rstrip(":")] = int(parts[1])
    return values


def read_psi():
    values = {}
    with open("/proc/pressure/memory", encoding="utf-8") as source:
        for line in source:
            parts = line.split()
            category = parts[0]
            for item in parts[1:]:
                key, value = item.split("=", 1)
                if key == "total":
                    values[f"psi_{category}_total_us"] = int(value)
    return values


def read_cpu_ticks():
    ticks = {}
    with open("/proc/stat", encoding="utf-8") as source:
        for line in source:
            parts = line.split()
            if not parts:
                continue
            if parts[0] in ("cpu", f"cpu{CPU}", f"cpu{SMT_SIBLING}"):
                ticks[parts[0]] = [int(value) for value in parts[1:]]
            elif parts[0] == "procs_running":
                ticks["procs_running"] = int(parts[1])
    return ticks


def cpu_nonidle_percent(previous, current, name):
    if previous is None:
        return ""
    before = previous[name]
    after = current[name]
    total = sum(after) - sum(before)
    idle = sum(after[3:5]) - sum(before[3:5])
    if total <= 0:
        return ""
    return 100.0 * (total - idle) / total


def competing_tasks(formal_pgid, monitor_pgid):
    result = subprocess.run(
        ["ps", "-eLo", "pid=,tid=,pgid=,psr=,stat=,comm="],
        check=True,
        text=True,
        capture_output=True,
    )
    competitors = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 5)
        if len(parts) != 6:
            continue
        pid, tid, pgid, psr, state, command = parts
        if int(psr) not in (CPU, SMT_SIBLING) or not state.startswith("R"):
            continue
        if int(pgid) in (formal_pgid, monitor_pgid):
            continue
        competitors.append(f"pid={pid},tid={tid},pgid={pgid},cpu={psr},stat={state},comm={command}")
    return ";".join(competitors)


def competitor_monitor(formal_pgid, monitor_pgid, start_monotonic, stop_event, rows):
    next_sample = start_monotonic
    while not stop_event.is_set():
        scan_start = time.monotonic()
        tasks = competing_tasks(formal_pgid, monitor_pgid)
        scan_end = time.monotonic()
        rows.append(
            {
                "timestamp_ns": time.time_ns(),
                "elapsed_seconds": scan_end - start_monotonic,
                "scan_seconds": scan_end - scan_start,
                "competing_runnable_tasks": tasks,
            }
        )
        next_sample += 1.0
        stop_event.wait(max(0.0, next_sample - time.monotonic()))


def sample(previous_cpu, start_monotonic):
    cpu = read_cpu_ticks()
    memory = read_key_values("/proc/meminfo")
    vmstat = read_key_values("/proc/vmstat")
    psi = read_psi()
    row = {
        "timestamp_ns": time.time_ns(),
        "elapsed_seconds": time.monotonic() - start_monotonic,
        "mem_total_kb": memory["MemTotal"],
        "mem_available_kb": memory["MemAvailable"],
        "pswpin_pages": vmstat["pswpin"],
        "pswpout_pages": vmstat["pswpout"],
        "psi_some_total_us": psi["psi_some_total_us"],
        "psi_full_total_us": psi["psi_full_total_us"],
        "procs_running": cpu["procs_running"],
        "system_nonidle_pct": cpu_nonidle_percent(previous_cpu, cpu, "cpu"),
        "cpu8_nonidle_pct": cpu_nonidle_percent(previous_cpu, cpu, f"cpu{CPU}"),
        "cpu200_nonidle_pct": cpu_nonidle_percent(
            previous_cpu, cpu, f"cpu{SMT_SIBLING}"
        ),
    }
    return cpu, row


def parse_elapsed(value):
    parts = value.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return float(value)


def parse_time_v(path):
    text = Path(path).read_text(encoding="utf-8")
    patterns = {
        "user_seconds": r"User time \(seconds\):\s*(\S+)",
        "system_seconds": r"System time \(seconds\):\s*(\S+)",
        "elapsed_text": r"Elapsed \(wall clock\) time.*:\s*(\S+)",
        "major_faults": r"Major \(requiring I/O\) page faults:\s*(\d+)",
        "minor_faults": r"Minor \(reclaiming a frame\) page faults:\s*(\d+)",
        "voluntary_context_switches": r"Voluntary context switches:\s*(\d+)",
        "involuntary_context_switches": r"Involuntary context switches:\s*(\d+)",
        "max_rss_kb": r"Maximum resident set size \(kbytes\):\s*(\d+)",
    }
    parsed = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if not match:
            raise RuntimeError(f"missing {key} in {path}")
        parsed[key] = match.group(1)
    for key in ("user_seconds", "system_seconds"):
        parsed[key] = float(parsed[key])
    for key in (
        "major_faults",
        "minor_faults",
        "voluntary_context_switches",
        "involuntary_context_switches",
        "max_rss_kb",
    ):
        parsed[key] = int(parsed[key])
    parsed["elapsed_seconds"] = parse_elapsed(parsed["elapsed_text"])
    parsed["cpu_utilization"] = (
        parsed["user_seconds"] + parsed["system_seconds"]
    ) / parsed["elapsed_seconds"]
    return parsed


def longest_high_cpu_run(rows):
    longest = current = 0
    for row in rows:
        value = row["system_nonidle_pct"]
        if value != "" and float(value) > 10.0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def immediate_violation(rows, competitor_rows):
    first = rows[0]
    current = rows[-1]
    mem_total_bytes = first["mem_total_kb"] * 1024
    min_available_bytes = min(row["mem_available_kb"] for row in rows) * 1024
    if current["procs_running"] > 4:
        return f"procs_running={current['procs_running']} > 4"
    if current["pswpout_pages"] != first["pswpout_pages"]:
        return "pswpout delta became nonzero"
    if current["psi_full_total_us"] != first["psi_full_total_us"]:
        return "memory PSI full delta became nonzero"
    if min_available_bytes < max(0.10 * mem_total_bytes, 8 * GIB):
        return "MemAvailable fell below the minimum"
    if (first["mem_available_kb"] * 1024 - min_available_bytes) > 0.05 * mem_total_bytes:
        return "MemAvailable drop exceeded 5% of MemTotal"
    if longest_high_cpu_run(rows) >= 5:
        return "system non-idle exceeded 10% for 5 consecutive samples"
    if any(row["competing_runnable_tasks"] for row in competitor_rows):
        return "competing runnable task observed on CPU 8/200"
    return None


def stop_timed_child(time_pid):
    children_path = Path(f"/proc/{time_pid}/task/{time_pid}/children")
    try:
        children = children_path.read_text(encoding="utf-8").split()
    except (FileNotFoundError, ProcessLookupError):
        return
    for child in children:
        try:
            os.kill(int(child), signal.SIGTERM)
        except ProcessLookupError:
            pass


def evaluate(
    label,
    rows,
    competitor_rows,
    time_data,
    process_elapsed_seconds,
    page_size,
    warm_exit,
    formal_exit,
    early_stop_reason,
):
    first, last = rows[0], rows[-1]
    elapsed_us = max(1.0, (last["elapsed_seconds"] - first["elapsed_seconds"]) * 1e6)
    mem_total_bytes = first["mem_total_kb"] * 1024
    min_available_kb = min(row["mem_available_kb"] for row in rows)
    min_available_bytes = min_available_kb * 1024
    available_drop_bytes = (
        first["mem_available_kb"] - min_available_kb
    ) * 1024
    pswpin_delta = last["pswpin_pages"] - first["pswpin_pages"]
    pswpout_delta = last["pswpout_pages"] - first["pswpout_pages"]
    psi_some_delta = last["psi_some_total_us"] - first["psi_some_total_us"]
    psi_full_delta = last["psi_full_total_us"] - first["psi_full_total_us"]
    window_seconds = elapsed_us / 1e6
    pswpin_rate = pswpin_delta * page_size / window_seconds
    competitors = [
        row["competing_runnable_tasks"]
        for row in competitor_rows
        if row["competing_runnable_tasks"]
    ]
    time_data["time_v_elapsed_seconds"] = time_data.pop("elapsed_seconds")
    time_data["process_elapsed_monotonic_seconds"] = process_elapsed_seconds
    time_data["cpu_utilization"] = (
        time_data["user_seconds"] + time_data["system_seconds"]
    ) / process_elapsed_seconds
    metrics = {
        "label": label,
        "warm_exit_code": warm_exit,
        "formal_exit_code": formal_exit,
        "early_stop_reason": early_stop_reason,
        **time_data,
        "sample_count": len(rows),
        "competitor_scan_count": len(competitor_rows),
        "max_competitor_scan_seconds": max(
            [row["scan_seconds"] for row in competitor_rows] or [0.0]
        ),
        "window_seconds": window_seconds,
        "page_size": page_size,
        "pswpin_start_pages": first["pswpin_pages"],
        "pswpin_end_pages": last["pswpin_pages"],
        "pswpin_delta_pages": pswpin_delta,
        "pswpin_bytes": pswpin_delta * page_size,
        "pswpin_rate_bytes_per_second": pswpin_rate,
        "pswpout_delta_pages": pswpout_delta,
        "psi_some_delta_us": psi_some_delta,
        "psi_some_fraction": psi_some_delta / elapsed_us,
        "psi_full_delta_us": psi_full_delta,
        "mem_total_bytes": mem_total_bytes,
        "mem_available_start_bytes": first["mem_available_kb"] * 1024,
        "mem_available_min_bytes": min_available_bytes,
        "mem_available_drop_bytes": available_drop_bytes,
        "max_procs_running": max(row["procs_running"] for row in rows),
        "longest_system_nonidle_over_10pct_samples": longest_high_cpu_run(rows),
        "max_system_nonidle_pct": max(
            [float(row["system_nonidle_pct"]) for row in rows if row["system_nonidle_pct"] != ""]
            or [0.0]
        ),
        "max_cpu8_nonidle_pct": max(
            [float(row["cpu8_nonidle_pct"]) for row in rows if row["cpu8_nonidle_pct"] != ""]
            or [0.0]
        ),
        "max_cpu200_nonidle_pct": max(
            [float(row["cpu200_nonidle_pct"]) for row in rows if row["cpu200_nonidle_pct"] != ""]
            or [0.0]
        ),
        "competing_runnable_tasks": competitors,
    }
    checks = {
        "warm_succeeded": warm_exit == 0,
        "formal_succeeded": formal_exit == 0,
        "major_faults_zero": time_data["major_faults"] == 0,
        "process_cpu_at_least_95pct": time_data["cpu_utilization"] >= 0.95,
        "pswpout_delta_zero": pswpout_delta == 0,
        "memory_psi_full_delta_zero": psi_full_delta == 0,
        "memory_psi_some_fraction_at_most_0_001": psi_some_delta / elapsed_us <= 0.001,
        "min_mem_available": min_available_bytes >= max(0.10 * mem_total_bytes, 8 * GIB),
        "mem_available_drop": available_drop_bytes <= 0.05 * mem_total_bytes,
        "procs_running_at_most_4": metrics["max_procs_running"] <= 4,
        "system_nonidle_not_high_for_5_samples": metrics[
            "longest_system_nonidle_over_10pct_samples"
        ] < 5,
        "no_cpu8_cpu200_competitor": not competitors,
        "pswpin_rate_at_most_1_mib_s": pswpin_rate <= MIB,
    }
    metrics["checks"] = checks
    metrics["advisories"] = (
        ["nonzero global pswpin; process major faults are checked separately"]
        if pswpin_delta > 0 and checks["major_faults_zero"]
        else []
    )
    metrics["passed"] = all(checks.values())
    return metrics


def write_markdown(path, metrics, commands):
    lines = [
        f"# Runtime gate: {metrics['label']}",
        "",
        f"**Status: {'PASS' if metrics['passed'] else 'FAIL'}**",
        "",
        "## Commands",
        "",
        "```text",
        *commands,
        "```",
        "",
        "## Process",
        "",
        f"- Major faults: {metrics['major_faults']}",
        f"- Minor faults: {metrics['minor_faults']}",
        f"- CPU utilization: {metrics['cpu_utilization']:.2%}",
        f"- User/system/monotonic elapsed: {metrics['user_seconds']:.2f}s / {metrics['system_seconds']:.2f}s / {metrics['process_elapsed_monotonic_seconds']:.2f}s",
        f"- Raw time -v elapsed: {metrics['time_v_elapsed_seconds']:.2f}s",
        f"- Voluntary context switches: {metrics['voluntary_context_switches']}",
        f"- Involuntary context switches: {metrics['involuntary_context_switches']}",
        f"- Maximum RSS: {metrics['max_rss_kb']} KiB",
        f"- Early stop reason: {metrics['early_stop_reason'] or 'none'}",
        "",
        "## System",
        "",
        f"- Samples: {metrics['sample_count']} over {metrics['window_seconds']:.3f}s",
        f"- Competitor scans: {metrics['competitor_scan_count']} (max scan {metrics['max_competitor_scan_seconds']:.3f}s)",
        f"- pswpin: {metrics['pswpin_start_pages']} -> {metrics['pswpin_end_pages']} pages; delta {metrics['pswpin_delta_pages']} pages / {metrics['pswpin_bytes']} bytes / {metrics['pswpin_rate_bytes_per_second']:.3f} B/s",
        f"- pswpout delta: {metrics['pswpout_delta_pages']} pages",
        f"- Memory PSI some/full delta: {metrics['psi_some_delta_us']} / {metrics['psi_full_delta_us']} us",
        f"- Memory PSI some fraction: {metrics['psi_some_fraction']:.6g}",
        f"- MemAvailable start/min/drop: {metrics['mem_available_start_bytes']} / {metrics['mem_available_min_bytes']} / {metrics['mem_available_drop_bytes']} bytes",
        f"- Maximum procs_running: {metrics['max_procs_running']}",
        f"- Maximum system non-idle: {metrics['max_system_nonidle_pct']:.2f}%",
        f"- Longest >10% system non-idle run: {metrics['longest_system_nonidle_over_10pct_samples']} samples",
        f"- Maximum CPU 8 / CPU 200 non-idle: {metrics['max_cpu8_nonidle_pct']:.2f}% / {metrics['max_cpu200_nonidle_pct']:.2f}%",
        f"- Competing runnable tasks: {len(metrics['competing_runnable_tasks'])}",
        "",
        "## Checks",
        "",
    ]
    for name, passed in metrics["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'}: `{name}`")
    if metrics["advisories"]:
        lines.extend(["", "## Advisories", ""])
        lines.extend(f"- {item}" for item in metrics["advisories"])
    lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    args = parse_args()
    binary = str(Path(args.binary).resolve())
    result_json = str(Path(args.result_json).resolve())
    runtime_dir = Path(args.runtime_dir).resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    if Path(result_json).exists():
        raise SystemExit(f"refusing to overwrite {result_json}")

    prefix = ["numactl", f"--physcpubind={CPU}", "--membind=0", binary]
    warm_command = prefix + [
        f"--benchmark_filter={WARM_FILTERS[args.label]}",
        "--benchmark_min_time=0.01s",
        "--benchmark_repetitions=1",
    ]
    if args.smoke:
        formal_command = prefix + [
            f"--benchmark_filter={SMOKE_FILTERS[args.label]}",
            "--benchmark_min_time=0.05s",
            "--benchmark_repetitions=1",
            f"--benchmark_out={result_json}",
            "--benchmark_out_format=json",
        ]
    else:
        formal_command = prefix + [
            "--benchmark_min_time=0.25s",
            "--benchmark_repetitions=7",
            "--benchmark_enable_random_interleaving=true",
            f"--benchmark_out={result_json}",
            "--benchmark_out_format=json",
        ]
    commands = [" ".join(warm_command), " ".join(formal_command)]
    (runtime_dir / f"{args.label}.commands.txt").write_text(
        "\n".join(commands) + "\n", encoding="utf-8"
    )

    with (runtime_dir / f"{args.label}.warm.log").open("w", encoding="utf-8") as log:
        warm = subprocess.run(
            warm_command,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "LC_ALL": "C"},
        )
    if warm.returncode != 0:
        raise SystemExit(f"warm invocation failed with {warm.returncode}")

    time_path = runtime_dir / f"{args.label}.time-v.txt"
    console_path = runtime_dir / f"{args.label}.formal-console.log"
    timed_command = ["/usr/bin/time", "-v", "-o", str(time_path), *formal_command]
    with console_path.open("w", encoding="utf-8") as console:
        formal = subprocess.Popen(
            timed_command,
            stdout=console,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "LC_ALL": "C"},
            start_new_session=True,
        )
        formal_pgid = formal.pid
        monitor_pgid = os.getpgrp()
        start_monotonic = time.monotonic()
        previous_cpu = None
        rows = []
        competitor_rows = []
        stop_competitor = threading.Event()
        competitor_thread = threading.Thread(
            target=competitor_monitor,
            args=(
                formal_pgid,
                monitor_pgid,
                start_monotonic,
                stop_competitor,
                competitor_rows,
            ),
            daemon=True,
        )
        competitor_thread.start()
        previous_cpu, row = sample(previous_cpu, start_monotonic)
        rows.append(row)
        sample_index = 1
        early_stop_reason = immediate_violation(rows, competitor_rows)
        if early_stop_reason:
            stop_timed_child(formal.pid)
        while True:
            timeout = max(
                0.0, start_monotonic + sample_index - time.monotonic()
            )
            try:
                formal_exit = formal.wait(timeout=timeout)
                process_end_monotonic = time.monotonic()
                break
            except subprocess.TimeoutExpired:
                previous_cpu, row = sample(previous_cpu, start_monotonic)
                rows.append(row)
                sample_index += 1
                early_stop_reason = immediate_violation(rows, competitor_rows)
                if early_stop_reason:
                    stop_timed_child(formal.pid)
        previous_cpu, row = sample(previous_cpu, start_monotonic)
        rows.append(row)
        stop_competitor.set()
        competitor_thread.join()
    process_elapsed_seconds = process_end_monotonic - start_monotonic

    samples_path = runtime_dir / f"{args.label}.samples.csv"
    with samples_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    competitor_path = runtime_dir / f"{args.label}.competitors.csv"
    with competitor_path.open("w", newline="", encoding="utf-8") as output:
        fields = [
            "timestamp_ns",
            "elapsed_seconds",
            "scan_seconds",
            "competing_runnable_tasks",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(competitor_rows)

    time_data = parse_time_v(time_path)
    metrics = evaluate(
        args.label,
        rows,
        competitor_rows,
        time_data,
        process_elapsed_seconds,
        resource.getpagesize(),
        warm.returncode,
        formal_exit,
        early_stop_reason,
    )
    gate_json = runtime_dir / f"{args.label}.gate.json"
    gate_md = runtime_dir / f"{args.label}.gate.md"
    gate_json.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    write_markdown(gate_md, metrics, commands)
    print(json.dumps({"label": args.label, "passed": metrics["passed"], "checks": metrics["checks"]}))
    return 0 if metrics["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
