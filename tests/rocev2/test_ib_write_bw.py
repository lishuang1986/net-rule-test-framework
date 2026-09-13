# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time
from tests.rocev2.utils import parse_ib_write_bw_output

pytestmark = [pytest.mark.rocev2]


def _run_ib_write_bw(rocev2_env, *, tag, tcpdump_filter,
                     server_addr=None, server_extra="", client_extra=""):
    """Run one ib_write_bw server/client round with packet capture.

    Starts tcpdump and the ib_write_bw server in background, runs the client
    (connecting to server_addr, default: server IPv4), then tears everything
    down and prints server/client logs and the capture.
    Logs go to /tmp/ib_write_bw_{server,client}_{tag}.log, capture to
    /tmp/ib_write_bw_{tag}.pcap.
    """
    client_if = rocev2_env.Client.get_iface()
    if server_addr is None:
        server_addr = rocev2_env.Server.get_ipv4()

    # Capture traffic in background (RoCEv2 UDP 4791, plus TCP 18515 when QP
    # info is exchanged over TCP instead of RDMA CM)
    tcpdump_proc = rocev2_env.Client.popen(
        f"tcpdump -U -i {client_if} {tcpdump_filter} "
        f"-w /tmp/ib_write_bw_{tag}.pcap"
    )
    time.sleep(1)

    # Start server in background. The iteration count must match the client's,
    # otherwise the server keeps waiting for iterations that will never arrive
    # and the client blocks in the socket sync until the server times out
    server_proc = rocev2_env.Server.popen(
        f"ib_write_bw {server_extra} -n 5 "
        f"> /tmp/ib_write_bw_server_{tag}.log 2>&1"
    )

    time.sleep(2)  # Wait for server to be ready

    try:
        # Run client, redirect output to file
        rocev2_env.Client.run(
            f"ib_write_bw {client_extra} {server_addr} -n 5 "
            f"> /tmp/ib_write_bw_client_{tag}.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Stop tcpdump and wait for buffer flush
        tcpdump_proc.terminate()
        tcpdump_proc.wait()
        time.sleep(1)

        # Print server output
        rocev2_env.Server.run(f"cat /tmp/ib_write_bw_server_{tag}.log")

        # Print client output
        rocev2_env.Client.run(f"cat /tmp/ib_write_bw_client_{tag}.log")

        # Display tcpdump capture
        rocev2_env.Client.run(f"tshark -r /tmp/ib_write_bw_{tag}.pcap")


def test_ib_write_bw_ipv4_rdma_cm(rocev2_env):
    """Test RDMA bandwidth using ib_write_bw with RDMA CM (-R)"""
    _run_ib_write_bw(
        rocev2_env,
        tag="ipv4",
        tcpdump_filter="udp port 4791",
        server_extra="-R",
        client_extra="-R",
    )


def test_ib_write_bw_ipv4_tcp_cm(rocev2_env):
    """Test RDMA bandwidth using ib_write_bw without -R (QP info over TCP 18515)"""
    _run_ib_write_bw(
        rocev2_env,
        tag="ipv4_noR",
        tcpdump_filter="udp port 4791 or tcp port 18515",
    )


def test_ib_write_bw_ipv6_rdma_cm(rocev2_env):
    """Test RDMA bandwidth over IPv6 using ib_write_bw with RDMA CM (-R)"""
    _run_ib_write_bw(
        rocev2_env,
        tag="ipv6",
        tcpdump_filter="udp port 4791",
        server_addr=rocev2_env.Server.get_ipv6(),
        server_extra="-R --ipv6-addr -x 2",
        client_extra="-R --ipv6-addr -x 2",
    )


def test_ib_write_bw_ipv6_tcp_cm(rocev2_env):
    """Test RDMA bandwidth over IPv6 without -R (QP info over TCP 18515)"""
    _run_ib_write_bw(
        rocev2_env,
        tag="ipv6_noR",
        tcpdump_filter="udp port 4791 or tcp port 18515",
        server_addr=rocev2_env.Server.get_ipv6(),
        server_extra="--ipv6-addr -x 2",
        client_extra="--ipv6-addr -x 2",
    )


def test_ib_write_bw_all(rocev2_env):
    """Run ib_write_bw -a (all tests in a single connection) with default parameters."""
    server_ip = rocev2_env.Server.get_ipv4()
    tag = "all"

    # Start server in background
    server_proc = rocev2_env.Server.popen(
        f"ib_write_bw -a > /tmp/ib_write_bw_server_{tag}.log 2>&1"
    )
    time.sleep(2)  # Wait for server to be ready

    try:
        # Run client (no capture, no extra flags)
        rocev2_env.Client.run(
            f"ib_write_bw -a {server_ip} "
            f"> /tmp/ib_write_bw_client_{tag}.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

    # Print server and client output
    rocev2_env.Server.run(f"cat /tmp/ib_write_bw_server_{tag}.log")
    rocev2_env.Client.run(f"cat /tmp/ib_write_bw_client_{tag}.log")


def test_ib_write_bw_bench_by_QP(rocev2_env):
    """Benchmark ib_write_bw bandwidth with different QP (Queue Pair) counts."""
    server_ip = rocev2_env.Server.get_ipv4()

    # -q : number of queue pairs to compare
    qp_values = [
        (1, "1QP"),
        (2, "2QP"),
        (4, "4QP"),
        (8, "8QP"),
        (16, "16QP"),
        (32, "32QP"),
    ]

    labels = []
    bw_data_list = []

    for qp_count, label in qp_values:
        print(f"\n--- Testing QP count: {label} ---")

        server_proc = rocev2_env.Server.popen(
            f"ib_write_bw -d rxe_server -R -x 1 -q {qp_count} "
            f"> /tmp/ib_write_bw_server_{label}.log 2>&1"
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


def test_ib_write_bw_bench_netem_loss(rocev2_env):
    """Benchmark ib_write_bw bandwidth with and without netem packet loss.

    Runs ib_write_bw under different netem loss rates on the client interface
    and prints a comparison table showing the performance impact of packet loss
    on RDMA Write bandwidth.
    """
    server_ip = rocev2_env.Server.get_ipv4()
    client_iface = rocev2_env.Client.get_iface()

    # Loss rates to test: (percentage, label)
    loss_values = [
        (0.0, "0%"),
        (0.01, "0.01%"),
        (0.05, "0.05%"),
        (0.1, "0.1%"),
        (0.5, "0.5%"),
    ]

    labels = []
    bw_data_list = []

    for loss_pct, label in loss_values:
        print(f"\n--- Testing netem loss: {label} ---")

        # Apply netem loss on the client egress (affects RDMA Write data path)
        if loss_pct > 0:
            rocev2_env.Client.run(
                f"tc qdisc add dev {client_iface} root netem loss {loss_pct}%"
            )

        server_proc = rocev2_env.Server.popen(
            f"ib_write_bw -d rxe_server -R -x 1 "
            f"> /tmp/ib_write_bw_server_loss{label}.log 2>&1"
        )
        time.sleep(2)
        try:
            rocev2_env.Client.run(
                f"ib_write_bw -d rxe_client -R -x 1 {server_ip} "
                f"> /tmp/ib_write_bw_client_loss{label}.log 2>&1"
            )
        finally:
            server_proc.terminate()
            server_proc.wait()

            # Clean up netem qdisc if applied
            if loss_pct > 0:
                rocev2_env.Client.run(f"tc qdisc del dev {client_iface} root")

        # Parse client output to get bandwidth metrics
        bw_data = parse_ib_write_bw_output(
            rocev2_env.Client, f"/tmp/ib_write_bw_client_loss{label}.log"
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
    print(f"ib_write_bw Bandwidth Comparison (netem loss):")
    print(f"{'=' * 70}")
    h = (f"{'Loss':<8} {'Iterations':<12} {'BW peak':<16} {'BW avg':<16} {'MsgRate':<12}")
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
