# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time

pytestmark = [pytest.mark.rocev2]


def _run_ib_write_lat(rocev2_env, *, tag, tcpdump_filter,
                      server_addr=None, server_extra="", client_extra=""):
    """Run one ib_write_lat server/client round with packet capture.

    Starts tcpdump and the ib_write_lat server in background, runs the client
    (connecting to server_addr, default: server IPv4), then tears everything
    down and prints server/client logs and the capture.
    Logs go to /tmp/ib_write_lat_{server,client}_{tag}.log, capture to
    /tmp/ib_write_lat_{tag}.pcap.
    """
    client_if = rocev2_env.Client.get_iface()
    if server_addr is None:
        server_addr = rocev2_env.Server.get_ipv4()

    # Capture traffic in background (RoCEv2 UDP 4791, plus TCP 18515 when QP
    # info is exchanged over TCP instead of RDMA CM)
    tcpdump_proc = rocev2_env.Client.popen(
        f"tcpdump -U -i {client_if} {tcpdump_filter} "
        f"-w /tmp/ib_write_lat_{tag}.pcap"
    )
    time.sleep(1)

    # Start server in background. The iteration count must match the client's,
    # otherwise the server keeps waiting for iterations that will never arrive
    # and the client blocks in the socket sync until the server times out
    server_proc = rocev2_env.Server.popen(
        f"ib_write_lat {server_extra} -n 5 "
        f"> /tmp/ib_write_lat_server_{tag}.log 2>&1"
    )

    time.sleep(2)  # Wait for server to be ready

    try:
        # Run client, redirect output to file
        rocev2_env.Client.run(
            f"ib_write_lat {client_extra} {server_addr} -n 5 "
            f"> /tmp/ib_write_lat_client_{tag}.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Stop tcpdump and wait for buffer flush
        tcpdump_proc.terminate()
        tcpdump_proc.wait()
        time.sleep(1)

        # Print server output
        rocev2_env.Server.run(f"cat /tmp/ib_write_lat_server_{tag}.log")

        # Print client output
        rocev2_env.Client.run(f"cat /tmp/ib_write_lat_client_{tag}.log")

        # Display tcpdump capture
        rocev2_env.Client.run(f"tshark -r /tmp/ib_write_lat_{tag}.pcap")


def test_ib_write_lat_ipv4_rdma_cm(rocev2_env):
    """Test RDMA latency using ib_write_lat with RDMA CM (-R)"""
    _run_ib_write_lat(
        rocev2_env,
        tag="ipv4",
        tcpdump_filter="udp port 4791",
        server_extra="-R",
        client_extra="-R",
    )


def test_ib_write_lat_ipv4_tcp_cm(rocev2_env):
    """Test RDMA latency using ib_write_lat without -R (QP info over TCP 18515)"""
    _run_ib_write_lat(
        rocev2_env,
        tag="ipv4_noR",
        tcpdump_filter="udp port 4791 or tcp port 18515",
    )


def test_ib_write_lat_ipv6_rdma_cm(rocev2_env):
    """Test RDMA latency over IPv6 using ib_write_lat with RDMA CM (-R)"""
    _run_ib_write_lat(
        rocev2_env,
        tag="ipv6",
        tcpdump_filter="udp port 4791",
        server_addr=rocev2_env.Server.get_ipv6(),
        server_extra="-R --ipv6-addr -x 2",
        client_extra="-R --ipv6-addr -x 2",
    )


def test_ib_write_lat_ipv6_tcp_cm(rocev2_env):
    """Test RDMA latency over IPv6 without -R (QP info over TCP 18515)"""
    _run_ib_write_lat(
        rocev2_env,
        tag="ipv6_noR",
        tcpdump_filter="udp port 4791 or tcp port 18515",
        server_addr=rocev2_env.Server.get_ipv6(),
        server_extra="--ipv6-addr -x 2",
        client_extra="--ipv6-addr -x 2",
    )


def test_ib_write_lat_all(rocev2_env):
    """Run ib_write_lat -a (all tests in a single connection) with default parameters."""
    server_ip = rocev2_env.Server.get_ipv4()
    tag = "all"

    # Start server in background
    server_proc = rocev2_env.Server.popen(
        f"ib_write_lat -a > /tmp/ib_write_lat_server_{tag}.log 2>&1"
    )
    time.sleep(2)  # Wait for server to be ready

    try:
        # Run client (no capture, no extra flags)
        rocev2_env.Client.run(
            f"ib_write_lat -a {server_ip} "
            f"> /tmp/ib_write_lat_client_{tag}.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

    # Print server and client output
    rocev2_env.Server.run(f"cat /tmp/ib_write_lat_server_{tag}.log")
    rocev2_env.Client.run(f"cat /tmp/ib_write_lat_client_{tag}.log")
