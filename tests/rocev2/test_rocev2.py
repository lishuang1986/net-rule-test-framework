# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest

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
