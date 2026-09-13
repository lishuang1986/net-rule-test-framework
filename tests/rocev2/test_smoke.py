# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time

pytestmark = [pytest.mark.rocev2]


def test_infiniband_diags(rocev2_env):
    """Verify ibstat, ibstatus, and ibnetdiscover diagnostic tools work"""
    # Server: ibstat
    rocev2_env.Server.run("ibstat")

    # Client: ibstat
    rocev2_env.Client.run("ibstat")

    # Server: ibstatus
    rocev2_env.Server.run("ibstatus")

    # Client: ibstatus
    rocev2_env.Client.run("ibstatus")


def test_libibverbs_utils(rocev2_env):
    """Verify RDMA devices are available via ibv_devinfo"""
    # Check server
    result = rocev2_env.Server.run("ibv_devinfo")
    assert "rxe_server" in result.stdout, "rxe_server not found in ibv_devinfo output"

    # Check client
    result = rocev2_env.Client.run("ibv_devinfo")
    assert "rxe_client" in result.stdout, "rxe_client not found in ibv_devinfo output"

    # Check server
    result = rocev2_env.Server.run("ibv_devices")
    assert "rxe_server" in result.stdout, "rxe_server not found in ibv_devices output"

    # Check client
    result = rocev2_env.Client.run("ibv_devices")
    assert "rxe_client" in result.stdout, "rxe_client not found in ibv_devices output"


def test_librdmacm_utils(rocev2_env):
    """Test basic RDMA connectivity using rdma_server/rdma_client"""
    server_ip = rocev2_env.Server.get_ipv4()

    # Start tcpdump in background to capture RoCEv2 traffic (UDP port 4791)
    client_if = rocev2_env.Client.get_iface()
    tcpdump_proc = rocev2_env.Client.popen(
        f"tcpdump -U -i {client_if} not port ssh -w /tmp/rdmacm_rocev2.pcap"
    )
    time.sleep(1)

    # Start rdma_server in background
    server_proc = rocev2_env.Server.popen(
        f"rdma_server > /tmp/rdma_server.log 2>&1"
    )
    time.sleep(2)

    try:
        # Run rdma_client (blocking)
        rocev2_env.Client.run(
            f"rdma_client -s {server_ip} > /tmp/rdma_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Stop tcpdump and wait for buffer flush
        tcpdump_proc.terminate()
        tcpdump_proc.wait()
        time.sleep(1)

        # Print and verify server log
        server_result = rocev2_env.Server.run("cat /tmp/rdma_server.log")
        client_result = rocev2_env.Client.run("cat /tmp/rdma_client.log")

        assert "rdma_server: start" in server_result.stdout
        assert "rdma_server: end 0" in server_result.stdout
        assert "rdma_client: start" in client_result.stdout
        assert "rdma_client: end 0" in client_result.stdout

        # Display tcpdump capture
        rocev2_env.Client.run("tshark -r /tmp/rdmacm_rocev2.pcap")
        rocev2_env.Client.run("tshark -r /tmp/rdmacm_rocev2.pcap -Y \"udp.port == 4791\"")
        rocev2_env.Client.run("tshark -r /tmp/rdmacm_rocev2.pcap -Y \"udp.port == 4791\" -O ip")


def _run_librdmacm_utils_trace(rocev2_env, kind):
    """Run rdma_server/rdma_client with trace-cmd recording on both nodes.

    Args:
        kind: "event" for rdma_cma/rdma_core event recording,
              "func" for function_graph recording.
    """
    server_ip = rocev2_env.Server.get_ipv4()

    if kind == "event":
        stem = "rdmacm_event"
        trace_args = "-e rdma_cma:* -e rdma_core:*"
        flush_sleep = 1
    else:  # "func"
        stem = "rdmacm_func"
        trace_args = "-p function_graph -l 'rxe_*' -l 'ib_*' -l 'rdma_*' -l 'cm_*'"
        flush_sleep = 3

    server_log = f"/tmp/{stem}_server.log"
    client_log = f"/tmp/{stem}_client.log"
    server_trace = f"/tmp/{stem}_server_trace.dat"
    client_trace = f"/tmp/{stem}_client_trace.dat"

    # Start rdma_server under trace-cmd recording on the server
    server_proc = rocev2_env.Server.popen(
        f"trace-cmd record {trace_args} -o {server_trace} "
        f"rdma_server > {server_log}"
    )
    time.sleep(2)

    try:
        # Run rdma_client under trace-cmd recording on the client (blocking).
        # trace-cmd exits and flushes its trace once rdma_client completes.
        rocev2_env.Client.run(
            f"trace-cmd record {trace_args} -o {client_trace} "
            f"rdma_client -s {server_ip} > {client_log}"
        )
    finally:
        # Give the server-side trace-cmd time to flush trace data to disk
        time.sleep(flush_sleep)
        server_proc.terminate()
        server_proc.wait()

        # Generate and display trace reports on both nodes
        rocev2_env.Server.run(f"trace-cmd report -i {server_trace}")
        rocev2_env.Client.run(f"trace-cmd report -i {client_trace}")

        # Print and verify logs
        server_result = rocev2_env.Server.run(f"cat {server_log}", check=False)
        client_result = rocev2_env.Client.run(f"cat {client_log}", check=False)

        assert "rdma_server: start" in server_result.stdout
        assert "rdma_server: end 0" in server_result.stdout
        assert "rdma_client: start" in client_result.stdout
        assert "rdma_client: end 0" in client_result.stdout


def test_librdmacm_utils_trace_event(rocev2_env):
    """Test rdma_server/rdma_client with trace-cmd rdma_cma/rdma_core event recording"""
    _run_librdmacm_utils_trace(rocev2_env, "event")


def test_librdmacm_utils_trace_func(rocev2_env):
    """Test rdma_server/rdma_client with trace-cmd function_graph recording"""
    _run_librdmacm_utils_trace(rocev2_env, "func")
