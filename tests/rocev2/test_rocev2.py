# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time

pytestmark = [pytest.mark.rocev2]


def test_rdma_device_available(rocev2_env):
    """Verify RDMA devices are available via ibv_devinfo"""
    # Check client
    result = rocev2_env.Client.run("ibv_devinfo")
    assert "rxe_client" in result.stdout, "rxe_client not found in ibv_devinfo output"

    # Check server
    result = rocev2_env.Server.run("ibv_devinfo")
    assert "rxe_server" in result.stdout, "rxe_server not found in ibv_devinfo output"


def test_network_connectivity_ipv4(rocev2_env):
    """Test IPv4 ping between client and server"""
    result = rocev2_env.Client.run(f"ping -c 3 -W 1 {rocev2_env.Server.get_ipv4()}")
    assert result.returncode == 0

    # Test RDMA connectivity using ibv_rc_pingpong
    server_ip = rocev2_env.Server.get_ipv4()
    server_proc = rocev2_env.Server.run(
        "ibv_rc_pingpong -d rxe_server -g 1 -n 5",
        background=True
    )
    time.sleep(2)
    try:
        result = rocev2_env.Client.run(
            f"ibv_rc_pingpong -d rxe_client -g 1 -n 5 {server_ip}",
            check=False
        )
        assert result.returncode == 0, f"ibv_rc_pingpong failed: {result.stderr}"
    finally:
        server_proc.terminate()
        server_proc.wait()


@pytest.mark.skip(reason="ibv_rc_pingpong IPv6 support has issues (gets stuck)")
def test_network_connectivity_ipv6(rocev2_env):
    """Test IPv6 ping between client and server via RDMA"""
    server_ipv6 = rocev2_env.Server.get_ipv6()

    # IPv4/6 ping first
    result = rocev2_env.Client.run(f"ping -6 -c 3 -W 1 {server_ipv6}")
    assert result.returncode == 0

    # Test RDMA connectivity using ibv_rc_pingpong (IPv6)
    # Use -g 2 for IPv6 GID index (GID[2]=2001:db8:1::x)
    server_proc = rocev2_env.Server.run(
        "ibv_rc_pingpong -d rxe_server -g 2 -n 5",
        background=True
    )
    time.sleep(2)
    try:
        result = rocev2_env.Client.run(
            f"ibv_rc_pingpong -d rxe_client -g 2 -n 5",
            check=False
        )
        assert result.returncode == 0, f"ibv_rc_pingpong (IPv6) failed: {result.stderr}"
    finally:
        server_proc.terminate()
        server_proc.wait()


def test_ib_write_bw(rocev2_env):
    """Test RDMA bandwidth using ib_write_bw (perftest)"""
    import time

    server_ip = rocev2_env.Server.get_ipv4()

    # Start server in background
    server_proc = rocev2_env.Server.run(
        "ib_write_bw -d rxe_server -R -x 1",
        background=True
    )

    time.sleep(2)  # Wait for server to be ready

    # Run client
    try:
        result = rocev2_env.Client.run(
            f"ib_write_bw -d rxe_client -R -x 1 {server_ip}",
            check=False
        )
        # ib_write_bw returns 0 on success
        assert result.returncode == 0, f"ib_write_bw failed: {result.stderr}"
        assert "MiB/sec" in result.stdout or "GiB/sec" in result.stdout
    finally:
        server_proc.terminate()
        server_proc.wait()


@pytest.mark.skip(reason="ib_write_bw IPv6 support has issues (Address family not supported)")
def test_ib_write_bw_ipv6(rocev2_env):
    """Test RDMA bandwidth over IPv6 using ib_write_bw"""
    import time

    server_ipv6 = rocev2_env.Server.get_ipv6()

    # Start server in background (use -g 2 for IPv6 GID index)
    server_proc = rocev2_env.Server.run(
        "ib_write_bw -d rxe_server -R -x 2",
        background=True
    )

    time.sleep(2)

    try:
        result = rocev2_env.Client.run(
            f"ib_write_bw -d rxe_client -R -x 2 {server_ipv6}",
            check=False
        )
        assert result.returncode == 0, f"ib_write_bw (IPv6) failed: {result.stderr}"
    finally:
        server_proc.terminate()
        server_proc.wait()
