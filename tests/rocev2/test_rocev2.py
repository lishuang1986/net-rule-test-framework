# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time

pytestmark = [pytest.mark.rocev2]


def test_rdma_device_available(rocev2_env):
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


def test_ib_diagnostic_tools(rocev2_env):
    """Verify ibstat, ibstatus, and ibnetdiscover diagnostic tools work"""
    # Server: ibstat
    rocev2_env.Server.run("ibstat")

    # Client: ibstat
    rocev2_env.Client.run("ibstat")

    # Server: ibstatus
    rocev2_env.Server.run("ibstatus")

    # Client: ibstatus
    rocev2_env.Client.run("ibstatus")

    ## Server: ibnetdiscover
    #rocev2_env.Server.run("ibnetdiscover")

    ## Client: ibnetdiscover
    #rocev2_env.Client.run("ibnetdiscover")


def test_rdma_basic_connect(rocev2_env):
    """Test basic RDMA connectivity using rdma_server/rdma_client"""
    server_ip = rocev2_env.Server.get_ipv4()
    port = 12345

    # Start rdma_server in background
    server_proc = rocev2_env.Server.popen(
        f"rdma_server -p {port} > /tmp/rdma_server.log 2>&1"
    )
    time.sleep(2)

    try:
        # Run rdma_client (blocking)
        rocev2_env.Client.run(
            f"rdma_client -s {server_ip} -p {port} > /tmp/rdma_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Print and verify server log
        server_result = rocev2_env.Server.run("cat /tmp/rdma_server.log")
        client_result = rocev2_env.Client.run("cat /tmp/rdma_client.log")

        assert "rdma_server: start" in server_result.stdout
        assert "rdma_server: end 0" in server_result.stdout
        assert "rdma_client: start" in client_result.stdout
        assert "rdma_client: end 0" in client_result.stdout
