# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import re


def parse_pingpong_time(host, log_file):
    """Parse ibv_rc_pingpong output and extract total time in seconds.

    Args:
        host: The VM/host object to run commands on
        log_file: Path to the ibv_rc_pingpong output log file

    Returns:
        Total time in seconds as float, or 0.0 if not found
    """
    result = host.run(f"cat {log_file} 2>/dev/null || echo ''")
    output = result.stdout

    # Pattern: "total time: X seconds" or "total time: X sec"
    match = re.search(r'total time:\s+([\d.]+)\s+(?:seconds|sec)', output)
    if match:
        return float(match.group(1))

    # Fallback pattern: any "X seconds" or "X sec" in output
    match = re.search(r'([\d.]+)\s+(?:seconds|sec)', output)
    if match:
        return float(match.group(1))

    return 0.0


def parse_perf_stat(host, log_file):
    """Parse perf stat output and extract metric values.

    Args:
        host: The VM/host object to run commands on
        log_file: Path to the perf stat output log file

    Returns:
        Dictionary containing parsed metrics
    """
    result = host.run(f"cat {log_file} 2>/dev/null || echo ''")
    output = result.stdout

    metrics = {
        'cycles': 0,
        'instructions': 0,
        'cache_references': 0,
        'cache_misses': 0,
        'context_switches': 0,
        'time_elapsed': 0,
        'user_time': 0,
        'sys_time': 0,
    }

    # For perf stat record, extract the stat section
    stat_section = ""
    in_stat_section = False

    for line in output.split('\n'):
        if line.strip().startswith("Performance counter stats:"):
            in_stat_section = True
            continue
        if in_stat_section and line.strip() == "":
            break
        if in_stat_section:
            stat_section += line + "\n"

    # If no stat section found, use the whole output
    if not stat_section:
        stat_section = output

    # Parse cycles
    match = re.search(r'([\d,]+)\s+cycles', stat_section)
    if match:
        metrics['cycles'] = int(match.group(1).replace(',', ''))

    # Parse instructions
    match = re.search(r'([\d,]+)\s+instructions', stat_section)
    if match:
        metrics['instructions'] = int(match.group(1).replace(',', ''))

    # Parse cache-references
    match = re.search(r'([\d,]+)\s+cache-references', stat_section)
    if match:
        metrics['cache_references'] = int(match.group(1).replace(',', ''))

    # Parse cache-misses
    match = re.search(r'([\d,]+)\s+cache-misses', stat_section)
    if match:
        metrics['cache_misses'] = int(match.group(1).replace(',', ''))

    # Parse context-switches
    match = re.search(r'([\d,]+)\s+context-switches', stat_section)
    if match:
        metrics['context_switches'] = int(match.group(1).replace(',', ''))

    # Parse time elapsed
    match = re.search(r'([\d.]+)\s+seconds time elapsed', stat_section)
    if match:
        metrics['time_elapsed'] = float(match.group(1))

    # Parse user and sys time (if available)
    match = re.search(r'([\d.]+)\s+seconds user\s+([\d.]+)\s+seconds sys', stat_section)
    if match:
        metrics['user_time'] = float(match.group(1))
        metrics['sys_time'] = float(match.group(2))

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
        List of tuples: [(overhead, symbol), ...] sorted by overhead descending
    """
    result = host.run(
        f"perf report --stdio --no-children --no-inline -F overhead,symbol -i {data_file}",
        silent=True,
        check=False
    )

    output = result.stdout

    if not output.strip():
        return []

    hotspots = []

    # Parse lines with format: "   XX.XX%  symbol_name"
    # Skip header lines (those starting with '#')
    for line in output.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # Match pattern like "   62.39%  rxe_post_send"
        match = re.match(r'([\d.]+)%\s+(.+)', line)
        if match:
            overhead = float(match.group(1))
            symbol = match.group(2).strip()
            hotspots.append((overhead, symbol))

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
    print("# Overhead  Symbol")
    print("# ........  .........................")
    for overhead, symbol in hotspots:
        print(f"    {overhead:6.2f}%  {symbol}")
