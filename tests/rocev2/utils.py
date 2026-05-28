# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import re


def parse_pingpong_output(host, log_file):
    """Parse ibv_pingpong output and extract all metrics.

    Calls ``host.run(f"cat {log_file}")`` once and parses all available
    fields from the output in a single pass.

    Args:
        host: The VM/host object to run commands on
        log_file: Path to the ibv_pingpong output log file

    Returns:
        Dict with the following keys (use ``.get()`` for optional fields):

        - **total_time_sec** (float) — always present, default 0.0
        - **bytes** (int) — total bytes transferred (optional)
        - **mbit_sec** (float) — throughput in Mbit/sec (optional)
        - **iters** (int) — number of iterations (optional)
        - **usec_iter** (float) — latency per iteration in us (optional)
    """
    result = host.run(f"cat {log_file} 2>/dev/null || echo ''")
    output = result.stdout
    data = {}

    # total time: "total time: X seconds" or "total time: X sec"
    match = re.search(r'total time:\s+([\d.]+)\s+(?:seconds|sec)', output)
    if match:
        data['total_time_sec'] = float(match.group(1))
    else:
        # Fallback: any "X seconds" or "X sec" in output
        match = re.search(r'([\d.]+)\s+(?:seconds|sec)', output)
        if match:
            data['total_time_sec'] = float(match.group(1))
        else:
            data['total_time_sec'] = 0.0

    # "102400 bytes in 0.29 seconds = 2.82 Mbit/sec"
    m = re.search(r'(\d+) bytes in ([\d.]+) seconds = ([\d.]+) Mbit/sec', output)
    if m:
        data['bytes'] = int(m.group(1))
        data['mbit_sec'] = float(m.group(3))

    # "1000 iters in 0.29 seconds = 291.72 usec/iter"
    m = re.search(r'(\d+) iters in ([\d.]+) seconds = ([\d.]+) usec/iter', output)
    if m:
        data['iters'] = int(m.group(1))
        data['usec_iter'] = float(m.group(3))

    return data


def parse_perf_stat_text(text):
    """Parse raw perf stat output text and return a dict of found metrics.

    Only metrics that appear in the output are included in the dict.
    Use ``.get(key, default)`` to handle missing keys.

    Supported metrics:
        cpu_migrations, task_clock, cycles, instructions, bus_cycles,
        cache_references, cache_misses, context_switches, time_elapsed,
        user_time, sys_time
    """
    metrics = {}

    # Locate the "Performance counter stats:" section if present
    stat_section = ""
    in_stat_section = False
    for line in text.split('\n'):
        if line.strip().startswith("Performance counter stats:"):
            in_stat_section = True
            continue
        if in_stat_section and line.strip() == "":
            break
        if in_stat_section:
            stat_section += line + "\n"

    if not stat_section:
        stat_section = text

    for line in stat_section.split('\n'):
        line = line.strip()
        if not line:
            continue

        # cpu-migrations: "NNN cpu-migrations"
        m = re.search(r'^([\d,]+)\s+cpu-migrations', line)
        if m:
            metrics['cpu_migrations'] = int(m.group(1).replace(',', ''))
            continue

        # task-clock: "NNN.NNN msec task-clock"
        m = re.search(r'^([\d,.]+)\s+(?:\S+\s+)?task-clock', line)
        if m:
            metrics['task_clock'] = float(m.group(1).replace(',', ''))
            continue

        # bus-cycles (must be checked before plain "cycles")
        m = re.search(r'^([\d,]+)\s+bus-cycles', line)
        if m:
            metrics['bus_cycles'] = int(m.group(1).replace(',', ''))
            continue

        # cycles
        m = re.search(r'^([\d,]+)\s+cycles', line)
        if m:
            metrics['cycles'] = int(m.group(1).replace(',', ''))
            continue

        # instructions
        m = re.search(r'^([\d,]+)\s+instructions', line)
        if m:
            metrics['instructions'] = int(m.group(1).replace(',', ''))
            continue

        # cache-references
        m = re.search(r'^([\d,]+)\s+cache-references', line)
        if m:
            metrics['cache_references'] = int(m.group(1).replace(',', ''))
            continue

        # cache-misses
        m = re.search(r'^([\d,]+)\s+cache-misses', line)
        if m:
            metrics['cache_misses'] = int(m.group(1).replace(',', ''))
            continue

        # context-switches
        m = re.search(r'^([\d,]+)\s+context-switches', line)
        if m:
            metrics['context_switches'] = int(m.group(1).replace(',', ''))
            continue

        # seconds user
        m = re.search(r'^([\d.]+)\s+seconds user', line)
        if m:
            metrics['user_time'] = float(m.group(1))
            continue

        # seconds sys
        m = re.search(r'^([\d.]+)\s+seconds sys', line)
        if m:
            metrics['sys_time'] = float(m.group(1))
            continue

        # seconds time elapsed
        m = re.search(r'^([\d.]+)\s+seconds time elapsed', line)
        if m:
            metrics['time_elapsed'] = float(m.group(1))
            continue

    return metrics


def parse_perf_stat(host, log_file):
    """Parse perf stat output from a remote file and extract metric values.

    Args:
        host: The VM/host object to run commands on
        log_file: Path to the perf stat output log file

    Returns:
        Dictionary containing parsed metrics (same keys as :func:`parse_perf_stat_text`)
    """
    result = host.run(f"cat {log_file} 2>/dev/null || echo ''")
    metrics = parse_perf_stat_text(result.stdout)
    # Backward compatibility: ensure all expected keys exist with 0 default
    for key in ('cycles', 'instructions', 'cache_references', 'cache_misses',
                'context_switches', 'time_elapsed', 'user_time', 'sys_time'):
        metrics.setdefault(key, 0)
    return metrics


def calculate_derived_metrics(metrics, pingpong_time=0.0):
    """Calculate derived metrics from raw perf data.

    Args:
        metrics: Dictionary containing raw perf metrics
        pingpong_time: Total time from ibv_rc_pingpong output in seconds.
                      If 0, falls back to perf stat's time_elapsed.

    Returns:
        Dictionary containing derived metrics (ipc, cache_miss_rate, ctx_switch_rate, cpu_util)
    """
    derived = {}

    if metrics['cycles'] > 0:
        derived['ipc'] = metrics['instructions'] / metrics['cycles']
    else:
        derived['ipc'] = 0

    if metrics['cache_references'] > 0:
        derived['cache_miss_rate'] = metrics['cache_misses'] / metrics['cache_references']
    else:
        derived['cache_miss_rate'] = 0

    # Use pingpong_time if available, otherwise fall back to time_elapsed
    time_base = pingpong_time if pingpong_time > 0 else metrics['time_elapsed']

    if time_base > 0:
        derived['ctx_switch_rate'] = metrics['context_switches'] / time_base
        derived['cpu_util'] = (metrics['user_time'] + metrics['sys_time']) / time_base
    else:
        derived['ctx_switch_rate'] = 0
        derived['cpu_util'] = 0

    return derived


def parse_perf_report(host, data_file):
    """Parse perf report output and extract hotspot functions.

    Args:
        host: The VM/host object to run commands on
        data_file: Path to the perf data file (.data extension)

    Returns:
        List of tuples: [(overhead, samples, symbol), ...] sorted by overhead descending
    """
    result = host.run(
        f"perf report --stdio -n --no-children --no-inline --no-call-graph -F overhead,sample,symbol -i {data_file} 2>&1",
        silent=True,
        check=False
    )

    output = result.stdout

    if not output.strip():
        return []

    hotspots = []

    # Parse lines with format: "   XX.XX%  NNNN  symbol_name"
    # Skip header lines (those starting with '#')
    for line in output.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # Match pattern like "   62.39%  623  rxe_post_send"
        match = re.match(r'([\d.]+)%\s+([\d,]+)\s+(.+)', line)
        if match:
            overhead = float(match.group(1))
            samples = int(match.group(2).replace(',', ''))
            symbol = match.group(3).strip()
            hotspots.append((overhead, samples, symbol))

    # Sort by overhead descending
    hotspots.sort(key=lambda x: x[0], reverse=True)

    return hotspots


def print_hotspot_report(hotspots, title):
    """Print formatted hotspot function report.

    Args:
        hotspots: List of tuples from parse_perf_report
        title: Section title for the report
    """
    print(f"\n{title}:")
    print("# Overhead  Samples  Symbol")
    print("# ........  .......  .........................")
    for overhead, samples, symbol in hotspots:
        print(f"    {overhead:6.2f}%  {samples:>6}  {symbol}")
