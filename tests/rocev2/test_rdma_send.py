# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import os
import pytest
import time

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
    log_suffix = f"rdma_send_{mode}"
    server_log = f"/tmp/{log_suffix}_server.log"
    client_log = f"/tmp/{log_suffix}_client.log"

    # Start server with specific mode in background
    server_proc = rocev2_env.Server.run(
        f"{BIN_SERVER} --mode {mode} > {server_log} 2>&1",
        background=True
    )
    time.sleep(2)

    try:
        # Run client with timeout to prevent hanging
        rocev2_env.Client.run(
            f"timeout {TIMEOUT} {BIN_CLIENT} {server_ip} > {client_log} 2>&1",
            check=False
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Print and verify outputs
        server_result = rocev2_env.Server.run(f"cat {server_log}", check=False)
        client_result = rocev2_env.Client.run(f"cat {client_log}", check=False)

        #print(f"[{mode}] Server log:\n{server_result.stdout}")
        #print(f"[{mode}] Client log:\n{client_result.stdout}")
        #if server_result.stderr:
        #    print(f"[{mode}] Server stderr:\n{server_result.stderr}")
        #if client_result.stderr:
        #    print(f"[{mode}] Client stderr:\n{client_result.stderr}")

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
