# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time
import plotext
from tests.rocev2.utils import (
    parse_pingpong_time,
    parse_perf_stat,
    calculate_derived_metrics,
    parse_perf_report,
    print_hotspot_report,
)

pytestmark = [pytest.mark.rocev2]


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


def test_ibv_uc_pingpong_ipv4(rocev2_env):
    """Test RDMA connectivity using ibv_uc_pingpong (Unreliable Connection)"""
    server_ip = rocev2_env.Server.get_ipv4()

    # Start server in background
    server_proc = rocev2_env.Server.run(
        "ibv_uc_pingpong -d rxe_server -g 1 -n 5 > /tmp/pingpong_uc_server.log 2>&1",
        background=True
    )
    time.sleep(2)
    try:
        rocev2_env.Client.run(
            f"ibv_uc_pingpong -d rxe_client -g 1 -n 5 {server_ip} > /tmp/pingpong_uc_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Print output
        rocev2_env.Server.run("cat /tmp/pingpong_uc_server.log")
        rocev2_env.Client.run("cat /tmp/pingpong_uc_client.log")

        rocev2_env.Client.run(f"ping -c 1 {server_ip}")


def test_ibv_ud_pingpong_ipv4(rocev2_env):
    """Test RDMA connectivity using ibv_ud_pingpong (Unreliable Datagram)"""
    server_ip = rocev2_env.Server.get_ipv4()

    # Start server in background
    server_proc = rocev2_env.Server.run(
        "ibv_ud_pingpong -d rxe_server -g 1 -n 5 > /tmp/pingpong_ud_server.log 2>&1",
        background=True
    )
    time.sleep(2)
    try:
        rocev2_env.Client.run(
            f"ibv_ud_pingpong -d rxe_client -g 1 -n 5 {server_ip} > /tmp/pingpong_ud_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Print output
        rocev2_env.Server.run("cat /tmp/pingpong_ud_server.log")
        rocev2_env.Client.run("cat /tmp/pingpong_ud_client.log")

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

        print(f"\n{'='*60}")
        print(f"Hotspot Functions Analysis ({label}):")
        print(f"{'='*60}")
        server_hotspots = parse_perf_report(rocev2_env.Server, f"/tmp/perf_data_server_{suffix}.data")
        client_hotspots = parse_perf_report(rocev2_env.Client, f"/tmp/perf_data_client_{suffix}.data")
        print_hotspot_report(server_hotspots, "Server Hotspots")
        print_hotspot_report(client_hotspots, "Client Hotspots")
