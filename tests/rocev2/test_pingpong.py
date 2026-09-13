# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time
import plotext
from tests.rocev2.utils import (
    parse_pingpong_output,
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

    # Start tcpdump in background to capture RoCEv2 traffic (UDP port 4791)
    tcpdump_proc = rocev2_env.Client.popen(
        f"tcpdump -U -i {client_iface} tcp port 18515 or udp port 4791 -w {pcap_file}"
    )
    time.sleep(1)

    # Start server in background, redirect output to file
    server_proc = rocev2_env.Server.popen(
        f"{binary} -g 1 -n 1 > /tmp/pingpong{log_suffix}_server.log 2>&1"
    )
    time.sleep(2)
    try:
        # Run client and redirect output to file
        rocev2_env.Client.run(
            f"{binary} -g 1 -n 1 {server_ip} > /tmp/pingpong{log_suffix}_client.log 2>&1"
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
        rocev2_env.Client.run(f"tshark -r {pcap_file} -Y \"tcp.port == 18515\"")
        rocev2_env.Client.run(f"tshark -r {pcap_file} -Y \"udp.port == 4791\"")
        #rocev2_env.Client.run(f"tcpdump -nn -r {pcap_file}")

        # Compare with regular ping
        rocev2_env.Client.run(f"ping -c 1 {server_ip}")


@pytest.mark.skip(reason="ibv_rc_pingpong IPv6 support has issues")
def test_ibv_rc_pingpong_ipv6(rocev2_env):
    """Test RDMA connectivity over IPv6 using ibv_rc_pingpong"""
    server_ipv6 = rocev2_env.Server.get_ipv6()

    # Use -g 2 for IPv6 GID index (GID[2]=2001:db8:1::x)
    server_proc = rocev2_env.Server.popen(
        "ibv_rc_pingpong -g 2 -n 1 > /tmp/pingpong_server_ipv6.log 2>&1"
    )
    time.sleep(2)
    try:
        # Run client and redirect output to file
        rocev2_env.Client.run(
            f"ibv_rc_pingpong -g 2 -n 1 {server_ipv6} > /tmp/pingpong_client_ipv6.log 2>&1"
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

        server_proc = rocev2_env.Server.popen(
            f"ibv_rc_pingpong -d rxe_server -g 1 -n {iterations} -s {msg_size} "
            f"> /tmp/pingpong_server_{label}.log 2>&1"
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
        client_lat = client_data.get('usec_iter', 0)
        server_lat = server_data.get('usec_iter', 0)
        client_latencies.append(client_lat)
        server_latencies.append(server_lat)
        print(f"  Client usec/iter: {client_lat:.2f}")
        print(f"  Server usec/iter: {server_lat:.2f}")

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
    plotext.ylabel('Latency per Iteration (usec)')
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
