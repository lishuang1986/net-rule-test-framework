# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time
import plotext

pytestmark = [pytest.mark.rocev2]


def test_rdma_device_available(rocev2_env):
    """Verify RDMA devices are available via ibv_devinfo"""
    # Check client
    result = rocev2_env.Client.run("ibv_devices")
    result = rocev2_env.Client.run("ibv_devinfo")
    assert "rxe_client" in result.stdout, "rxe_client not found in ibv_devinfo output"

    # Check server
    result = rocev2_env.Server.run("ibv_devices")
    result = rocev2_env.Server.run("ibv_devinfo")
    assert "rxe_server" in result.stdout, "rxe_server not found in ibv_devinfo output"


def test_rping_ipv4(rocev2_env):
    """Test RDMA connectivity between client and server using rping"""
    server_ip = rocev2_env.Server.get_ipv4()

    # Start rping server in background (listen on all interfaces)
    server_proc = rocev2_env.Server.run(
        "rping -s -d rxe_server -C 5 -v -a 0.0.0.0 > /tmp/rping_server.log 2>&1",
        background=True
    )
    time.sleep(2)
    try:
        # Run rping client (connect to server IP)
        rocev2_env.Client.run(
            f"rping -c -d rxe_client -C 5 -v -a {server_ip} > /tmp/rping_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Print server output
        rocev2_env.Server.run("cat /tmp/rping_server.log")

        # Print client output
        rocev2_env.Client.run("cat /tmp/rping_client.log")


def test_ibv_rc_pingpong_ipv4(rocev2_env):
    """Test RDMA connectivity between client and server using ibv_rc_pingpong"""
    server_ip = rocev2_env.Server.get_ipv4()

    # Start server in background, redirect output to file
    server_proc = rocev2_env.Server.run(
        "ibv_rc_pingpong -d rxe_server -g 1 -n 5 > /tmp/pingpong_server.log 2>&1",
        background=True
    )
    time.sleep(2)
    try:
        # Run client and redirect output to file
        rocev2_env.Client.run(
            f"ibv_rc_pingpong -d rxe_client -g 1 -n 5 {server_ip} > /tmp/pingpong_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Print server output
        rocev2_env.Server.run("cat /tmp/pingpong_server.log")

        # Print client output
        rocev2_env.Client.run("cat /tmp/pingpong_client.log")

        # Compare with regular ping
        rocev2_env.Client.run(f"ping -c 1 {server_ip}")


@pytest.mark.skip(reason="rping/ibv_rc_pingpong IPv6 support has issues")
def test_ibv_rc_pingpong_ipv6(rocev2_env):
    """Test RDMA connectivity over IPv6 using ibv_rc_pingpong"""
    server_ipv6 = rocev2_env.Server.get_ipv6()

    # Use -g 2 for IPv6 GID index (GID[2]=2001:db8:1::x)
    server_proc = rocev2_env.Server.run(
        "ibv_rc_pingpong -d rxe_server -g 2 -n 5 > /tmp/pingpong_server_ipv6.log 2>&1",
        background=True
    )
    time.sleep(2)
    try:
        # Run client and redirect output to file
        rocev2_env.Client.run(
            f"ibv_rc_pingpong -d rxe_client -g 2 -n 5 > /tmp/pingpong_client_ipv6.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Print server output
        rocev2_env.Server.run("cat /tmp/pingpong_server_ipv6.log")

        # Print client output
        rocev2_env.Client.run("cat /tmp/pingpong_client_ipv6.log")

        # Compare with regular ping over IPv6
        rocev2_env.Client.run(f"ping -c 1 {server_ipv6}")


def test_ib_write_bw(rocev2_env):
    """Test RDMA bandwidth using ib_write_bw (perftest)"""
    import time

    server_ip = rocev2_env.Server.get_ipv4()

    # Start server in background
    server_proc = rocev2_env.Server.run(
        "ib_write_bw -d rxe_server -R -x 1",
        background=True
    )

    time.sleep(2)  # Wait for server to be ready

    # Run client
    try:
        result = rocev2_env.Client.run(
            f"ib_write_bw -d rxe_client -R -x 1 {server_ip}"
        )
        assert "MiB/sec" in result.stdout or "GiB/sec" in result.stdout
    finally:
        server_proc.terminate()
        server_proc.wait()


@pytest.mark.skip(reason="ib_write_bw/rping IPv6 support has issues")
def test_ib_write_bw_ipv6(rocev2_env):
    """Test RDMA bandwidth over IPv6 using ib_write_bw"""
    import time

    server_ipv6 = rocev2_env.Server.get_ipv6()

    # Start server in background (use -g 2 for IPv6 GID index)
    server_proc = rocev2_env.Server.run(
        "ib_write_bw -d rxe_server -R -x 2",
        background=True
    )

    time.sleep(2)

    try:
        result = rocev2_env.Client.run(
            f"ib_write_bw -d rxe_client -R -x 2 {server_ipv6}"
        )
        assert "MiB/sec" in result.stdout or "GiB/sec" in result.stdout
    finally:
        server_proc.terminate()
        server_proc.wait()


def test_ibv_rc_pingpong_latency_by_size(rocev2_env):
    """Test ibv_rc_pingpong latency at different message sizes and plot comparison."""
    server_ip = rocev2_env.Server.get_ipv4()
    iterations = 100

    sizes = [
        (1, "1B"),
        (1024, "1K"),
        (4096, "4K"),
        (8192, "8K"),
        (16384, "16K"),
    ]

    labels = []
    client_latencies = []
    server_latencies = []

    for msg_size, label in sizes:
        print(f"\n--- Testing Message Size: {label} ---")

        server_proc = rocev2_env.Server.run(
            f"ibv_rc_pingpong -d rxe_server -g 1 -n {iterations} -s {msg_size} "
            f"> /tmp/pingpong_server_{label}.log 2>&1",
            background=True
        )
        time.sleep(2)
        try:
            rocev2_env.Client.run(
                f"ibv_rc_pingpong -d rxe_client -g 1 -n {iterations} -s {msg_size} "
                f"{server_ip} > /tmp/pingpong_client_{label}.log 2>&1"
            )
        finally:
            server_proc.terminate()
            server_proc.wait()

        t_client = parse_pingpong_time(rocev2_env.Client, f"/tmp/pingpong_client_{label}.log")
        t_server = parse_pingpong_time(rocev2_env.Server, f"/tmp/pingpong_server_{label}.log")
        labels.append(label)
        client_latencies.append(t_client / iterations)
        server_latencies.append(t_server / iterations)
        print(f"  Client total: {t_client:.6f}s, Latency per iter: {t_client/iterations:.6f}s")
        print(f"  Server total: {t_server:.6f}s, Latency per iter: {t_server/iterations:.6f}s")

    # ========================================
    # Plot latency comparison
    # ========================================
    print("\n" + "=" * 60)
    print("Latency Comparison Chart:")
    print("=" * 60)
    x_indices = list(range(len(labels)))
    plotext.plot(x_indices, client_latencies, marker='braille', label='Client')
    plotext.plot(x_indices, server_latencies, marker='braille', label='Server')
    plotext.xticks(x_indices, labels)
    plotext.title('ibv_rc_pingpong Latency by Message Size')
    plotext.xlabel('Message Size')
    plotext.ylabel('Latency per Iteration (sec)')
    plotext.show()

    print("\nLatency Summary (from ibv_rc_pingpong output):")
    for label, cl, sl in zip(labels, client_latencies, server_latencies):
        print(f"   {label}:  Client {cl*1_000_000:.2f} us, Server {sl*1_000_000:.2f} us per iteration")
    print("=" * 60)


def test_ibv_rc_pingpong_perf_stat(rocev2_env):
    """Perf stat monitoring for ibv_rc_pingpong across message sizes."""
    server_ip = rocev2_env.Server.get_ipv4()

    rocev2_env.Client.run("mkdir -p /tmp/perf_data")
    rocev2_env.Server.run("mkdir -p /tmp/perf_data")

    perf_events = "cycles,instructions,cache-references,cache-misses,context-switches"
    iterations = 1000

    sizes = [
        (1, "1b", "1B"),
        (1024, "1k", "1K"),
        (4096, "4k", "4K"),
        (8192, "8k", "8K"),
        (16384, "16k", "16K"),
    ]

    labels = []
    server_derived_list = []
    client_derived_list = []

    for msg_size, suffix, label in sizes:
        print(f"\n--- Testing Message Size: {label} ---")

        server_proc = rocev2_env.Server.run(
            f"perf stat -e {perf_events} -o /tmp/perf_stat_server_{suffix}.txt -- "
            f"ibv_rc_pingpong -d rxe_server -g 1 -n {iterations} -s {msg_size} "
            f"> /tmp/pingpong_server_{suffix}.log 2>&1",
            background=True
        )
        time.sleep(2)
        try:
            rocev2_env.Client.run(
                f"perf stat -e {perf_events} -o /tmp/perf_stat_client_{suffix}.txt -- "
                f"ibv_rc_pingpong -d rxe_client -g 1 -n {iterations} -s {msg_size} "
                f"{server_ip} > /tmp/pingpong_client_{suffix}.log 2>&1"
            )
        finally:
            server_proc.terminate()
            server_proc.wait()

        pingpong_time_server = parse_pingpong_time(rocev2_env.Server, f"/tmp/pingpong_server_{suffix}.log")
        pingpong_time_client = parse_pingpong_time(rocev2_env.Client, f"/tmp/pingpong_client_{suffix}.log")
        server_metrics = parse_perf_stat(rocev2_env.Server, f"/tmp/perf_stat_server_{suffix}.txt")
        client_metrics = parse_perf_stat(rocev2_env.Client, f"/tmp/perf_stat_client_{suffix}.txt")

        labels.append(label)
        server_derived_list.append(calculate_derived_metrics(server_metrics, pingpong_time_server))
        client_derived_list.append(calculate_derived_metrics(client_metrics, pingpong_time_client))

    # ========================================
    # Comparison Summary
    # ========================================
    print("\n" + "=" * 60)
    print("Comparison Summary:")
    print("=" * 60)

    print("\n1. IPC (Instructions Per Cycle) = instructions / cycles")
    for label, sd, cd in zip(labels, server_derived_list, client_derived_list):
        print(f"   Server - {label}:  {sd.get('ipc', 0):.4f}")
        print(f"   Client - {label}:  {cd.get('ipc', 0):.4f}")

    print("\n2. Cache Miss Rate = cache-misses / cache-references")
    for label, sd, cd in zip(labels, server_derived_list, client_derived_list):
        print(f"   Server - {label}:  {sd.get('cache_miss_rate', 0)*100:.4f}%")
        print(f"   Client - {label}:  {cd.get('cache_miss_rate', 0)*100:.4f}%")

    print("\n3. Context Switch Rate = context-switches / time_elapsed")
    for label, sd, cd in zip(labels, server_derived_list, client_derived_list):
        print(f"   Server - {label}:  {sd.get('ctx_switch_rate', 0):.4f}/sec")
        print(f"   Client - {label}:  {cd.get('ctx_switch_rate', 0):.4f}/sec")

    print("\n4. CPU Utilization = (user + sys) / elapsed")
    for label, sd, cd in zip(labels, server_derived_list, client_derived_list):
        print(f"   Server - {label}:  {sd.get('cpu_util', 0)*100:.4f}%")
        print(f"   Client - {label}:  {cd.get('cpu_util', 0)*100:.4f}%")

    print("=" * 60)


def test_ibv_rc_pingpong_perf_record(rocev2_env):
    """Perf record/report hotspot analysis for ibv_rc_pingpong across message sizes."""
    server_ip = rocev2_env.Server.get_ipv4()

    rocev2_env.Client.run("mkdir -p /tmp/perf_data")
    rocev2_env.Server.run("mkdir -p /tmp/perf_data")

    iterations = 1000

    sizes = [
        (1, "1b", "1B"),
        (1024, "1k", "1K"),
        (4096, "4k", "4K"),
        (8192, "8k", "8K"),
        (16384, "16k", "16K"),
        (65536, "64k", "64K"),
        (131072, "128k", "128K"),
        (1048576, "1m", "1M"),
    ]

    for msg_size, suffix, label in sizes:
        print(f"\n--- Testing Message Size: {label} ---")

        server_proc = rocev2_env.Server.run(
            f"perf record -F 4000 -g -o /tmp/perf_data_server_{suffix}.data "
            f"ibv_rc_pingpong -d rxe_server -g 1 -n {iterations} -s {msg_size} "
            f"> /tmp/pingpong_server_{suffix}.log 2>&1",
            background=True
        )
        time.sleep(2)
        try:
            rocev2_env.Client.run(
                f"perf record -F 4000 -g -o /tmp/perf_data_client_{suffix}.data "
                f"ibv_rc_pingpong -d rxe_client -g 1 -n {iterations} -s {msg_size} "
                f"{server_ip} > /tmp/pingpong_client_{suffix}.log 2>&1"
            )
        finally:
            server_proc.terminate()
            server_proc.wait()

        ## Debug print
        #rocev2_env.Server.run(f"ls -lh /tmp/perf_data_server_{suffix}.data")
        #rocev2_env.Client.run(f"ls -lh /tmp/perf_data_client_{suffix}.data")
        #rocev2_env.Server.run(f"perf report --header-only -i /tmp/perf_data_server_{suffix}.data 2>&1")
        #rocev2_env.Client.run(f"perf report --header-only -i /tmp/perf_data_client_{suffix}.data 2>&1")

        print(f"\n{'='*60}")
        print(f"Hotspot Functions Analysis ({label}):")
        print(f"{'='*60}")
        server_hotspots = parse_perf_report(rocev2_env.Server, f"/tmp/perf_data_server_{suffix}.data")
        client_hotspots = parse_perf_report(rocev2_env.Client, f"/tmp/perf_data_client_{suffix}.data")
        print_hotspot_report(server_hotspots, "Server Hotspots")
        print_hotspot_report(client_hotspots, "Client Hotspots")


# ========================================
# Helper functions for performance monitoring
# ========================================
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

    import re

    # For perf stat record, we need to extract the stat section
    # Look for the stat section which typically starts with performance counter stats
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

    import re

    # Pattern: "total time: X seconds" or "total time: X sec"
    match = re.search(r'total time:\s+([\d.]+)\s+(?:seconds|sec)', output)
    if match:
        return float(match.group(1))

    # Fallback pattern: any "X seconds" or "X sec" in output
    match = re.search(r'([\d.]+)\s+(?:seconds|sec)', output)
    if match:
        return float(match.group(1))

    return 0.0


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

    import re

    hotspots = []
    total_lines = 0
    matched_lines = 0

    # Parse lines with format: "   XX.XX%  symbol_name"
    # Skip header lines (those starting with '#')
    for line in output.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        total_lines += 1

        # Match pattern like "   62.39%  rxe_post_send"
        match = re.match(r'([\d.]+)%\s+(.+)', line)
        if match:
            matched_lines += 1
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
