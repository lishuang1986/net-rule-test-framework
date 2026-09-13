# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time

pytestmark = [pytest.mark.rocev2]


def _run_rping(rocev2_env, tag, server_bind_addr, server_ip):
    """Start rping server, run rping client, and capture RoCEv2 traffic.

    Args:
        tag: Label used for log/pcap file names (e.g. "ipv4", "ipv6")
        server_bind_addr: Address the rping server binds to (-a on server)
        server_ip: Address the rping client connects to
    """
    client_if = rocev2_env.Client.get_iface()
    server_log = f"/tmp/rping_{tag}_server.log"
    client_log = f"/tmp/rping_{tag}_client.log"
    pcap_file = f"/tmp/rping_{tag}.pcap"

    # Start tcpdump in background to capture RoCEv2 traffic (UDP port 4791)
    tcpdump_proc = rocev2_env.Client.popen(
        f"tcpdump -U -i {client_if} udp port 4791 -w {pcap_file}"
    )
    time.sleep(1)

    # Start rping server in background
    server_proc = rocev2_env.Server.popen(
        f"rping -s -d rxe_server -C 1 -v -a {server_bind_addr} > {server_log} 2>&1"
    )
    time.sleep(2)
    try:
        # Run rping client
        rocev2_env.Client.run(
            f"rping -c -d rxe_client -C 1 -v -a {server_ip} > {client_log} 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Stop tcpdump and wait for buffer flush
        tcpdump_proc.terminate()
        tcpdump_proc.wait()
        time.sleep(1)

        # Print server output
        rocev2_env.Server.run(f"cat {server_log}")

        # Print client output
        rocev2_env.Client.run(f"cat {client_log}")

        # Display tcpdump capture
        rocev2_env.Client.run(f"tshark -r {pcap_file}")
        rocev2_env.Client.run(f"tcpdump -nnvv -r {pcap_file}")


def test_rping_ipv4(rocev2_env):
    """Test RDMA connectivity between client and server using rping (IPv4)"""
    _run_rping(
        rocev2_env,
        tag="ipv4",
        server_bind_addr="0.0.0.0",
        server_ip=rocev2_env.Server.get_ipv4(),
    )


def test_rping_ipv6(rocev2_env):
    """Test RDMA connectivity between client and server using rping (IPv6)"""
    _run_rping(
        rocev2_env,
        tag="ipv6",
        server_bind_addr="::1",
        server_ip=rocev2_env.Server.get_ipv6(),
    )
