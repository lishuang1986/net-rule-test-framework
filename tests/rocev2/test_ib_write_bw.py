# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time
from tests.rocev2.utils import parse_ib_write_bw_output

pytestmark = [pytest.mark.rocev2]


def test_ib_write_bw(rocev2_env):
    """Test RDMA bandwidth using ib_write_bw (perftest)"""
    client_ip = rocev2_env.Client.get_ipv4()
    server_ip = rocev2_env.Server.get_ipv4()

    # Start server in background
    server_proc = rocev2_env.Server.run(
        "ib_write_bw -d rxe_server -R -x 1 > /tmp/ib_write_bw_server.log 2>&1",
        background=True
    )

    time.sleep(2)  # Wait for server to be ready

    try:
        # Run client, redirect output to file
        rocev2_env.Client.run(
            f"ib_write_bw -d rxe_client -R -x 1 {server_ip} > /tmp/ib_write_bw_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Print server output
        rocev2_env.Server.run("cat /tmp/ib_write_bw_server.log")

        # Print client output
        rocev2_env.Client.run("cat /tmp/ib_write_bw_client.log")


@pytest.mark.skip(reason="ib_write_bw/rping IPv6 support has issues")
def test_ib_write_bw_ipv6(rocev2_env):
    """Test RDMA bandwidth over IPv6 using ib_write_bw"""
    server_ipv6 = rocev2_env.Server.get_ipv6()

    # Start server in background (use -g 2 for IPv6 GID index)
    server_proc = rocev2_env.Server.run(
        "ib_write_bw -d rxe_server -R -x 2 > /tmp/ib_write_bw_server_ipv6.log 2>&1",
        background=True
    )

    time.sleep(2)

    try:
        rocev2_env.Client.run(
            f"ib_write_bw -d rxe_client -R -x 2 {server_ipv6} > /tmp/ib_write_bw_client_ipv6.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Print server output
        rocev2_env.Server.run("cat /tmp/ib_write_bw_server_ipv6.log")

        # Print client output
        rocev2_env.Client.run("cat /tmp/ib_write_bw_client_ipv6.log")


def test_ib_write_bw_bench_by_mtu(rocev2_env):
    """Benchmark ib_write_bw bandwidth with different active MTU sizes (fixed 1MB message)."""
    client_ip = rocev2_env.Client.get_ipv4()
    server_ip = rocev2_env.Server.get_ipv4()

    # Set link MTU to 9000 on both nodes
    for node in [rocev2_env.Client, rocev2_env.Server]:
        node.run(f"sudo ip link set dev {node.get_iface()} mtu 9000")
        node.run("ibv_devinfo | grep -i mtu")
        node.run("ibv_devinfo -v | grep -i qp")

    # Ping with DF flag and large payload to verify end-to-end MTU
    for node, peer_ip in [(rocev2_env.Client, server_ip), (rocev2_env.Server, client_ip)]:
        node.run(f"ping -M do -s 8972 {peer_ip} -c 1")

    # -s : message size (total transfer per op), fixed at 1MB
    # -m : active MTU size to compare
    msg_size = 1048576  # 1MB
    mtu_sizes = [
        (1024, "1K"),
        (2048, "2K"),
        (4096, "4K"),
    ]

    labels = []
    bw_data_list = []

    for mtu_size, label in mtu_sizes:
        print(f"\n--- Testing active MTU: {label} ---")

        server_proc = rocev2_env.Server.run(
            f"ib_write_bw -d rxe_server -R -x 1 -s {msg_size} -m {mtu_size} "
            f"> /tmp/ib_write_bw_server_mtu{label}.log 2>&1",
            background=True
        )
        time.sleep(2)
        try:
            rocev2_env.Client.run(
                f"ib_write_bw -d rxe_client -R -x 1 -s {msg_size} -m {mtu_size} {server_ip} "
                f"> /tmp/ib_write_bw_client_mtu{label}.log 2>&1"
            )
        finally:
            server_proc.terminate()
            server_proc.wait()

        # Parse client output to get bandwidth metrics
        bw_data = parse_ib_write_bw_output(
            rocev2_env.Client, f"/tmp/ib_write_bw_client_mtu{label}.log"
        )
        labels.append(label)
        bw_data_list.append(bw_data)

        bw_avg = bw_data.get('bw_avg_mb_sec', 0)
        bw_peak = bw_data.get('bw_peak_mb_sec', 0)
        msgs = bw_data.get('iterations', 0)
        print(f"  Iterations: {msgs}, BW avg: {bw_avg:.2f} MB/sec, BW peak: {bw_peak:.2f} MB/sec")

    # ========================================
    # Bandwidth comparison table
    # ========================================
    print(f"\n{'=' * 70}")
    print(f"ib_write_bw Bandwidth Comparison (message size = {msg_size} bytes):")
    print(f"{'=' * 70}")
    h = (f"{'MTU':<8} {'Iterations':<12} {'BW peak':<16} {'BW avg':<16} {'MsgRate':<12}")
    sep = "-" * len(h)
    print(h)
    print(sep)
    for label, d in zip(labels, bw_data_list):
        _iters = str(d.get('iterations', 'N/A'))
        _peak  = f"{d.get('bw_peak_mb_sec', 0):.2f} MB/s" if d.get('bw_peak_mb_sec') else 'N/A'
        _avg   = f"{d.get('bw_avg_mb_sec', 0):.2f} MB/s" if d.get('bw_avg_mb_sec') else 'N/A'
        _rate  = f"{d.get('msg_rate_mpps', 0):.6f}" if d.get('msg_rate_mpps') else 'N/A'
        print(f"{label:<8} {_iters:<12} {_peak:<16} {_avg:<16} {_rate:<12}")
    print(f"{'=' * 70}")


def test_ib_write_bw_bench_by_QP(rocev2_env):
    """Benchmark ib_write_bw bandwidth with different QP (Queue Pair) counts."""
    server_ip = rocev2_env.Server.get_ipv4()

    # -q : number of queue pairs to compare
    qp_values = [
        (1, "1QP"),
        (2, "2QP"),
        (4, "4QP"),
        (8, "8QP"),
    ]

    labels = []
    bw_data_list = []

    for qp_count, label in qp_values:
        print(f"\n--- Testing QP count: {label} ---")

        server_proc = rocev2_env.Server.run(
            f"ib_write_bw -d rxe_server -R -x 1 -q {qp_count} "
            f"> /tmp/ib_write_bw_server_{label}.log 2>&1",
            background=True
        )
        time.sleep(2)
        try:
            rocev2_env.Client.run(
                f"ib_write_bw -d rxe_client -R -x 1 -q {qp_count} {server_ip} "
                f"> /tmp/ib_write_bw_client_{label}.log 2>&1"
            )
        finally:
            server_proc.terminate()
            server_proc.wait()

        # Parse client output to get bandwidth metrics
        bw_data = parse_ib_write_bw_output(
            rocev2_env.Client, f"/tmp/ib_write_bw_client_{label}.log"
        )
        labels.append(label)
        bw_data_list.append(bw_data)

        bw_avg = bw_data.get('bw_avg_mb_sec', 0)
        bw_peak = bw_data.get('bw_peak_mb_sec', 0)
        msgs = bw_data.get('iterations', 0)
        print(f"  Iterations: {msgs}, BW avg: {bw_avg:.2f} MB/sec, BW peak: {bw_peak:.2f} MB/sec")

    # ========================================
    # Bandwidth comparison table
    # ========================================
    print(f"\n{'=' * 70}")
    print(f"ib_write_bw Bandwidth Comparison by QP count:")
    print(f"{'=' * 70}")
    h = (f"{'QP':<8} {'Iterations':<12} {'BW peak':<16} {'BW avg':<16} {'MsgRate':<12}")
    sep = "-" * len(h)
    print(h)
    print(sep)
    for label, d in zip(labels, bw_data_list):
        _iters = str(d.get('iterations', 'N/A'))
        _peak  = f"{d.get('bw_peak_mb_sec', 0):.2f} MB/s" if d.get('bw_peak_mb_sec') else 'N/A'
        _avg   = f"{d.get('bw_avg_mb_sec', 0):.2f} MB/s" if d.get('bw_avg_mb_sec') else 'N/A'
        _rate  = f"{d.get('msg_rate_mpps', 0):.6f}" if d.get('msg_rate_mpps') else 'N/A'
        print(f"{label:<8} {_iters:<12} {_peak:<16} {_avg:<16} {_rate:<12}")
    print(f"{'=' * 70}")
