# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time

pytestmark = [pytest.mark.rocev2]


def test_rping_ipv4(rocev2_env):
    """Test RDMA connectivity between client and server using rping"""
    server_ip = rocev2_env.Server.get_ipv4()
    client_if = rocev2_env.Client.get_iface()

    # Start tcpdump in background to capture RoCEv2 traffic (UDP port 4791)
    tcpdump_proc = rocev2_env.Client.run(
        f"tcpdump -U -i {client_if} udp port 4791 -w /tmp/rping_rocev2.pcap", background=True
    )
    time.sleep(1)

    # Start rping server in background (listen on all interfaces)
    server_proc = rocev2_env.Server.run(
        "rping -s -d rxe_server -C 3 -v -a 0.0.0.0 > /tmp/rping_server.log 2>&1",
        background=True
    )
    time.sleep(2)
    try:
        # Run rping client (connect to server IP)
        rocev2_env.Client.run(
            f"rping -c -d rxe_client -C 3 -v -a {server_ip} > /tmp/rping_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Stop tcpdump and wait for buffer flush
        tcpdump_proc.terminate()
        tcpdump_proc.wait()
        time.sleep(1)

        # Print server output
        rocev2_env.Server.run("cat /tmp/rping_server.log")

        # Print client output
        rocev2_env.Client.run("cat /tmp/rping_client.log")

        # Display tcpdump capture 
        rocev2_env.Client.run("tshark -r /tmp/rping_rocev2.pcap")
        rocev2_env.Client.run("tcpdump -nn -r /tmp/rping_rocev2.pcap")
