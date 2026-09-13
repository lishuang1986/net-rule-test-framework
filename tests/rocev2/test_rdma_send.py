# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import os
import pytest
import time
from tests.rocev2.utils import parse_perf_stat_output, parse_perf_report, print_hotspot_report

pytestmark = [pytest.mark.rocev2]

_dir = os.path.dirname(__file__)
SRC_SERVER = os.path.join(_dir, "rdma_send_server.c")
SRC_CLIENT = os.path.join(_dir, "rdma_send_client.c")
DST_SERVER = "/tmp/rdma_send_server.c"
DST_CLIENT = "/tmp/rdma_send_client.c"
BIN_SERVER = "/tmp/rdma_send_server"
BIN_CLIENT = "/tmp/rdma_send_client"
TIMEOUT = 20


def _setup(rocev2_env):
    """Copy sources and compile on both nodes."""
    rocev2_env.Server.get(SRC_SERVER, DST_SERVER)
    rocev2_env.Client.get(SRC_CLIENT, DST_CLIENT)
    rocev2_env.Server.run(f"gcc -o {BIN_SERVER} {DST_SERVER} -lrdmacm -libverbs")
    rocev2_env.Client.run(f"gcc -o {BIN_CLIENT} {DST_CLIENT} -lrdmacm -libverbs")


def _run_test(rocev2_env, mode, server_assert):
    server_ip = rocev2_env.Server.get_ipv4()
    client_iface = rocev2_env.Client.get_iface()
    log_suffix = f"rdma_send_{mode}"
    server_log = f"/tmp/{log_suffix}_server.log"
    client_log = f"/tmp/{log_suffix}_client.log"
    pcap_file = f"/tmp/{log_suffix}.pcap"

    # Start tcpdump in background to capture RoCEv2 traffic (UDP port 4791)
    tcpdump_proc = rocev2_env.Client.popen(
        f"tcpdump -U -i {client_iface} tcp port 7474 or udp port 4791 -w {pcap_file}"
    )
    time.sleep(1)

    # Start server with specific mode in background
    server_proc = rocev2_env.Server.popen(
        f"{BIN_SERVER} --mode {mode} > {server_log} 2>&1"
    )
    time.sleep(2)

    try:
        # Run client with timeout to prevent hanging
        rocev2_env.Client.run(
            f"timeout {TIMEOUT} {BIN_CLIENT} --mode {mode} {server_ip} > {client_log} 2>&1",
            check=False
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Stop tcpdump and wait for buffer flush
        tcpdump_proc.terminate()
        tcpdump_proc.wait()
        time.sleep(1)

        # Print and verify outputs
        server_result = rocev2_env.Server.run(f"cat {server_log}", check=False)
        client_result = rocev2_env.Client.run(f"cat {client_log}", check=False)

        # Display tcpdump capture — RoCEv2 (UDP 4791)
        rocev2_env.Client.run(f"tshark -r {pcap_file} -Y \"udp.port == 4791\"")
        # Display tcpdump capture — RDMA_CM over TCP (7474)
        rocev2_env.Client.run(f"tshark -r {pcap_file} -Y \"tcp.port == 7474\"")
        rocev2_env.Client.run(f"tcpdump -nn -r {pcap_file}")

        assert server_assert in server_result.stdout, \
            f"Server ({mode}) did not receive expected message"
        assert "Data sent successfully" in client_result.stdout, \
            f"Client ({mode}) did not report send success"


def test_rdma_send_poll(rocev2_env):
    """Test RDMA send with server in polling mode"""
    _setup(rocev2_env)
    _run_test(rocev2_env, "poll", "[Polling Mode] Received data: Hello RDMA")


def test_rdma_send_event(rocev2_env):
    """Test RDMA send with server in event-driven mode"""
    _setup(rocev2_env)
    _run_test(rocev2_env, "event", "[Event-Driven] Received data: Hello RDMA")


def test_rdma_send_hybrid(rocev2_env):
    """Test RDMA send with server in hybrid mode"""
    _setup(rocev2_env)
    _run_test(rocev2_env, "hybrid", "Received data: Hello RDMA")
