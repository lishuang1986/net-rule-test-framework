# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time

pytestmark = [pytest.mark.rocev2]


def _run_ib_send_bw(rocev2_env, *, tag, tcpdump_filter,
                    server_addr=None, server_extra="", client_extra="",
                    server_ingress_loss=None):
    """Run one ib_send_bw server/client round with packet capture.

    Starts tcpdump and the ib_send_bw server in background, runs the client
    (connecting to server_addr, default: server IPv4), then tears everything
    down and prints server/client logs and the capture.
    Logs go to /tmp/ib_send_bw_{server,client}_{tag}.log, capture to
    /tmp/ib_send_bw_{tag}.pcap.
    server_ingress_loss, if set, drops that percentage of the RoCEv2 data
    packets (UDP 4791, matched by an ingress flower filter) arriving at the
    server. Control traffic (e.g. TCP 18515 CM) is left untouched. The
    client-side capture then shows each lost packet plus its retransmission
    (same PSN twice).
    """
    client_if = rocev2_env.Client.get_iface()
    server_if = rocev2_env.Server.get_iface()
    if server_addr is None:
        server_addr = rocev2_env.Server.get_ipv4()

    # Optionally drop only client -> server RoCEv2 data at the server ingress so
    # RC retransmissions appear as duplicate packets in the capture
    if server_ingress_loss is not None:
        proto = "ipv6" if ":" in server_addr else "ip"
        rocev2_env.Server.run("modprobe ifb", check=False)
        rocev2_env.Server.run("ip link add name ifb0 type ifb")
        rocev2_env.Server.run("ip link set dev ifb0 up")
        rocev2_env.Server.run(f"tc qdisc add dev {server_if} ingress")
        rocev2_env.Server.run(
            f"tc filter add dev {server_if} ingress protocol {proto} flower "
            f"ip_proto udp dst_port 4791 action mirred egress redirect dev ifb0"
        )
        rocev2_env.Server.run(
            f"tc qdisc add dev ifb0 root netem loss {server_ingress_loss}%"
        )

    # Capture traffic in background (RoCEv2 UDP 4791, plus TCP 18515 when QP
    # info is exchanged over TCP instead of RDMA CM)
    tcpdump_proc = rocev2_env.Client.popen(
        f"tcpdump -U -i {client_if} {tcpdump_filter} "
        f"-w /tmp/ib_send_bw_{tag}.pcap"
    )
    time.sleep(1)

    # Start server in background. The iteration count must match the client's,
    # otherwise the server keeps waiting for iterations that will never arrive
    # and the client blocks in the socket sync until the server times out
    server_proc = rocev2_env.Server.popen(
        f"ib_send_bw {server_extra} -n 5 "
        f"> /tmp/ib_send_bw_server_{tag}.log 2>&1"
    )

    time.sleep(2)  # Wait for server to be ready

    try:
        # Run client, redirect output to file
        rocev2_env.Client.run(
            f"ib_send_bw {client_extra} {server_addr} -n 5 "
            f"> /tmp/ib_send_bw_client_{tag}.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Stop tcpdump and wait for buffer flush
        tcpdump_proc.terminate()
        tcpdump_proc.wait()
        time.sleep(1)

        # Show the ingress shaping stats (how many packets netem dropped and
        # how many the ingress qdisc/filter saw), then tear it all down
        if server_ingress_loss is not None:
            rocev2_env.Server.run("tc -s qdisc show dev ifb0", check=False)
            rocev2_env.Server.run(
                f"tc -s qdisc show dev {server_if}", check=False
            )
            rocev2_env.Server.run(
                f"tc -s filter show dev {server_if} ingress", check=False
            )
            rocev2_env.Server.run("tc qdisc del dev ifb0 root", check=False)
            rocev2_env.Server.run(
                f"tc qdisc del dev {server_if} ingress", check=False
            )
            rocev2_env.Server.run("ip link del ifb0", check=False)

        # Print server output
        rocev2_env.Server.run(f"cat /tmp/ib_send_bw_server_{tag}.log")

        # Print client output
        rocev2_env.Client.run(f"cat /tmp/ib_send_bw_client_{tag}.log")

        # Display tcpdump capture
        rocev2_env.Client.run(f"tshark -r /tmp/ib_send_bw_{tag}.pcap")


def test_ib_send_bw_ipv4_rdma_cm(rocev2_env):
    """Test RDMA bandwidth using ib_send_bw with RDMA CM (-R)"""
    _run_ib_send_bw(
        rocev2_env,
        tag="ipv4",
        tcpdump_filter="udp port 4791",
        server_extra="-R",
        client_extra="-R",
    )


def test_ib_send_bw_ipv4_tcp_cm(rocev2_env):
    """Test RDMA bandwidth using ib_send_bw without -R (QP info over TCP 18515)"""
    _run_ib_send_bw(
        rocev2_env,
        tag="ipv4_noR",
        tcpdump_filter="udp port 4791 or tcp port 18515",
    )


def test_ib_send_bw_ipv6_rdma_cm(rocev2_env):
    """Test RDMA bandwidth over IPv6 using ib_send_bw with RDMA CM (-R)"""
    _run_ib_send_bw(
        rocev2_env,
        tag="ipv6",
        tcpdump_filter="udp port 4791",
        server_addr=rocev2_env.Server.get_ipv6(),
        server_extra="-R --ipv6-addr -x 2",
        client_extra="-R --ipv6-addr -x 2",
    )


def test_ib_send_bw_ipv6_tcp_cm(rocev2_env):
    """Test RDMA bandwidth over IPv6 without -R (QP info over TCP 18515)"""
    _run_ib_send_bw(
        rocev2_env,
        tag="ipv6_noR",
        tcpdump_filter="udp port 4791 or tcp port 18515",
        server_addr=rocev2_env.Server.get_ipv6(),
        server_extra="--ipv6-addr -x 2",
        client_extra="--ipv6-addr -x 2",
    )


def test_ib_send_bw_ipv4_tcp_cm_netem_loss(rocev2_env):
    """Test ib_send_bw over IPv4 TCP CM with 2% (1/50) server ingress loss.

    QP info goes over TCP 18515 (control, untouched) while 2% of the RoCEv2
    data packets (UDP 4791) arriving at the server are dropped, so the
    client-side capture shows RC retransmissions as duplicate PSNs.
    """
    _run_ib_send_bw(
        rocev2_env,
        tag="ipv4_noR_loss",
        tcpdump_filter="udp port 4791 or tcp port 18515",
        server_ingress_loss=2,
    )


def test_ib_send_bw_ipv6_tcp_cm_netem_loss(rocev2_env):
    """Test ib_send_bw over IPv6 TCP CM with 2% (1/50) server ingress loss."""
    _run_ib_send_bw(
        rocev2_env,
        tag="ipv6_noR_loss",
        tcpdump_filter="udp port 4791 or tcp port 18515",
        server_addr=rocev2_env.Server.get_ipv6(),
        server_extra="--ipv6-addr -x 2",
        client_extra="--ipv6-addr -x 2",
        server_ingress_loss=2,
    )


def test_ib_send_bw_ipv4_rdma_cm_netem_loss(rocev2_env):
    """Test ib_send_bw over IPv4 RDMA CM with 2% (1/50) server ingress loss.

    With -R both the CM exchange and the data ride RoCEv2 (UDP 4791), so the
    ingress loss also hits connection setup; RDMA CM retransmits, so the
    connection still comes up and the capture shows RC retransmissions.
    """
    _run_ib_send_bw(
        rocev2_env,
        tag="ipv4_loss",
        tcpdump_filter="udp port 4791",
        server_extra="-R",
        client_extra="-R",
        server_ingress_loss=2,
    )


def test_ib_send_bw_ipv6_rdma_cm_netem_loss(rocev2_env):
    """Test ib_send_bw over IPv6 RDMA CM with 2% (1/50) server ingress loss."""
    _run_ib_send_bw(
        rocev2_env,
        tag="ipv6_loss",
        tcpdump_filter="udp port 4791",
        server_addr=rocev2_env.Server.get_ipv6(),
        server_extra="-R --ipv6-addr -x 2",
        client_extra="-R --ipv6-addr -x 2",
        server_ingress_loss=2,
    )


def test_ib_send_bw_all(rocev2_env):
    """Run ib_send_bw -a (all tests in a single connection) with default parameters."""
    server_ip = rocev2_env.Server.get_ipv4()
    tag = "all"

    # Start server in background
    server_proc = rocev2_env.Server.popen(
        f"ib_send_bw -a > /tmp/ib_send_bw_server_{tag}.log 2>&1"
    )
    time.sleep(2)  # Wait for server to be ready

    try:
        # Run client (no capture, no extra flags)
        rocev2_env.Client.run(
            f"ib_send_bw -a {server_ip} "
            f"> /tmp/ib_send_bw_client_{tag}.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

    # Print server and client output
    rocev2_env.Server.run(f"cat /tmp/ib_send_bw_server_{tag}.log")
    rocev2_env.Client.run(f"cat /tmp/ib_send_bw_client_{tag}.log")
