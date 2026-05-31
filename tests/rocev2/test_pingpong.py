# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time
import plotext
from tests.rocev2.utils import (
    parse_pingpong_output,
    parse_perf_stat,
    parse_perf_stat_text,
    calculate_derived_metrics,
    parse_perf_report,
    print_hotspot_report,
)

pytestmark = [pytest.mark.rocev2]


@pytest.mark.parametrize("transport,log_suffix", [
    ("rc", ""),
    ("uc", "_uc"),
    ("ud", "_ud"),
], ids=["rc", "uc", "ud"])
def test_ibv_pingpong_ipv4(rocev2_env, transport, log_suffix):
    """Test RDMA connectivity using ibv_{rc,uc,ud}_pingpong over IPv4"""
    server_ip = rocev2_env.Server.get_ipv4()
    client_iface = rocev2_env.Client.get_iface()
    binary = f"ibv_{transport}_pingpong"
    pcap_file = f"/tmp/pingpong{log_suffix}.pcap"
    port = "18515"

    # Start tcpdump in background to capture RoCEv2 traffic (UDP port 4791)
    tcpdump_proc = rocev2_env.Client.run(
        f"tcpdump -U -i {client_iface} tcp port {port} or udp port 4791 -w {pcap_file}",
        background=True
    )
    time.sleep(1)

    # Start server in background, redirect output to file
    server_proc = rocev2_env.Server.run(
        f"{binary} -d rxe_server -g 1 -n 3 -p {port} > /tmp/pingpong{log_suffix}_server.log 2>&1",
        background=True
    )
    time.sleep(2)
    try:
        # Run client and redirect output to file
        rocev2_env.Client.run(
            f"{binary} -d rxe_client -g 1 -n 3 -p {port} {server_ip} > /tmp/pingpong{log_suffix}_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Stop tcpdump and wait for buffer flush
        tcpdump_proc.terminate()
        tcpdump_proc.wait()
        time.sleep(1)

        # Print server output
        rocev2_env.Server.run(f"cat /tmp/pingpong{log_suffix}_server.log")

        # Print client output
        rocev2_env.Client.run(f"cat /tmp/pingpong{log_suffix}_client.log")

        # Display tcpdump capture — RoCEv2 (UDP 4791)
        rocev2_env.Client.run(f"tshark -r {pcap_file} -Y \"udp.port == 4791\"")
        rocev2_env.Client.run(f"tcpdump -nn -r {pcap_file}")

        # Compare with regular ping
        rocev2_env.Client.run(f"ping -c 1 {server_ip}")


@pytest.mark.skip(reason="rping/ibv_rc_pingpong IPv6 support has issues")
def test_ibv_rc_pingpong_ipv6(rocev2_env):
    """Test RDMA connectivity over IPv6 using ibv_rc_pingpong"""
    server_ipv6 = rocev2_env.Server.get_ipv6()

    # Use -g 2 for IPv6 GID index (GID[2]=2001:db8:1::x)
    server_proc = rocev2_env.Server.run(
        "ibv_rc_pingpong -d rxe_server -g 2 -n 3 > /tmp/pingpong_server_ipv6.log 2>&1",
        background=True
    )
    time.sleep(2)
    try:
        # Run client and redirect output to file
        rocev2_env.Client.run(
            f"ibv_rc_pingpong -d rxe_client -g 2 -n 3 > /tmp/pingpong_client_ipv6.log 2>&1"
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


def test_ibv_rc_pingpong_bench_by_size(rocev2_env):
    """Benchmark ibv_rc_pingpong latency and throughput at different message sizes."""
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
    client_data_list = []
    server_data_list = []
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

        client_data = parse_pingpong_output(rocev2_env.Client, f"/tmp/pingpong_client_{label}.log")
        server_data = parse_pingpong_output(rocev2_env.Server, f"/tmp/pingpong_server_{label}.log")
        labels.append(label)
        client_data_list.append(client_data)
        server_data_list.append(server_data)
        t_client = client_data['total_time_sec']
        t_server = server_data['total_time_sec']
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

    # ========================================
    # Throughput table
    # ========================================
    print("\n" + "=" * 60)
    print("ibv_rc_pingpong Throughput / Latency:")
    print("=" * 60)
    h1 = (f"{'Size':<8} {'Side':<8} {'Bytes':<10} {'Mbit/sec':<12} {'usec/iter':<12}")
    sep1 = "-" * len(h1)
    print(h1)
    print(sep1)
    for label, sd, cd in zip(labels, server_data_list, client_data_list):
        _b_s = str(sd.get('bytes', 'N/A'))
        _b_c = str(cd.get('bytes', 'N/A'))
        _m_s = f"{sd.get('mbit_sec', 0):.2f}" if sd.get('mbit_sec') else 'N/A'
        _m_c = f"{cd.get('mbit_sec', 0):.2f}" if cd.get('mbit_sec') else 'N/A'
        _u_s = f"{sd.get('usec_iter', 0):.2f}" if sd.get('usec_iter') else 'N/A'
        _u_c = f"{cd.get('usec_iter', 0):.2f}" if cd.get('usec_iter') else 'N/A'
        print(f"{label:<8} {'Server':<8} {_b_s:<10} {_m_s:<12} {_u_s:<12}")
        print(f"{label:<8} {'Client':<8} {_b_c:<10} {_m_c:<12} {_u_c:<12}")
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
    server_raw_list = []
    client_raw_list = []
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

        server_data = parse_pingpong_output(rocev2_env.Server, f"/tmp/pingpong_server_{suffix}.log")
        client_data = parse_pingpong_output(rocev2_env.Client, f"/tmp/pingpong_client_{suffix}.log")
        server_metrics = parse_perf_stat(rocev2_env.Server, f"/tmp/perf_stat_server_{suffix}.txt")
        client_metrics = parse_perf_stat(rocev2_env.Client, f"/tmp/perf_stat_client_{suffix}.txt")

        labels.append(label)
        server_raw_list.append(server_metrics)
        client_raw_list.append(client_metrics)
        server_derived_list.append(calculate_derived_metrics(server_metrics, server_data['total_time_sec']))
        client_derived_list.append(calculate_derived_metrics(client_metrics, client_data['total_time_sec']))


    # ========================================
    # Table 2: Perf Stat Raw Counters
    # ========================================
    print(f"\n=== Perf Stat — Raw Counters ===")
    h2 = (f"{'Size':<8} {'Side':<8} {'Cycles':<14} {'Instructions':<16} "
          f"{'Cache Ref':<14} {'Cache Miss':<14} {'Ctx Switch':<14}")
    sep2 = "-" * len(h2)
    print(h2)
    print(sep2)
    for label, sr, cr in zip(labels, server_raw_list, client_raw_list):
        _cy_s = str(sr.get('cycles', 'N/A'))
        _cy_c = str(cr.get('cycles', 'N/A'))
        _in_s = str(sr.get('instructions', 'N/A'))
        _in_c = str(cr.get('instructions', 'N/A'))
        _cr_s = str(sr.get('cache_references', 'N/A'))
        _cr_c = str(cr.get('cache_references', 'N/A'))
        _cm_s = str(sr.get('cache_misses', 'N/A'))
        _cm_c = str(cr.get('cache_misses', 'N/A'))
        _cs_s = str(sr.get('context_switches', 'N/A'))
        _cs_c = str(cr.get('context_switches', 'N/A'))
        print(f"{label:<8} {'Server':<8} {_cy_s:<14} {_in_s:<16} {_cr_s:<14} {_cm_s:<14} {_cs_s:<14}")
        print(f"{label:<8} {'Client':<8} {_cy_c:<14} {_in_c:<16} {_cr_c:<14} {_cm_c:<14} {_cs_c:<14}")

    # ========================================
    # Table 3: Derived Metrics
    # ========================================
    print(f"\n=== Perf Stat — Derived Metrics ===")
    h3 = (f"{'Size':<8} {'Side':<8} {'IPC':<10} {'Cache Miss Rate':<18} {'Ctx Switch Rate':<16} {'CPU Util':<14}")
    sep3 = "-" * len(h3)
    print(h3)
    print(sep3)
    for label, sd, cd in zip(labels, server_derived_list, client_derived_list):
        _ipc_s = f"{sd.get('ipc', 0):.4f}"
        _ipc_c = f"{cd.get('ipc', 0):.4f}"
        _cm_s  = f"{sd.get('cache_miss_rate', 0)*100:.4f}%"
        _cm_c  = f"{cd.get('cache_miss_rate', 0)*100:.4f}%"
        _cs_s  = f"{sd.get('ctx_switch_rate', 0):.4f}/s"
        _cs_c  = f"{cd.get('ctx_switch_rate', 0):.4f}/s"
        _cu_s  = f"{sd.get('cpu_util', 0)*100:.4f}%"
        _cu_c  = f"{cd.get('cpu_util', 0)*100:.4f}%"
        print(f"{label:<8} {'Server':<8} {_ipc_s:<10} {_cm_s:<18} {_cs_s:<16} {_cu_s:<14}")
        print(f"{label:<8} {'Client':<8} {_ipc_c:<10} {_cm_c:<18} {_cs_c:<16} {_cu_c:<14}")

    print("\n" + "=" * 60)


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
