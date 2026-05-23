# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time

pytestmark = [pytest.mark.rocev2]


def test_ib_write_bw(rocev2_env):
    """Test RDMA bandwidth using ib_write_bw (perftest)"""
    server_ip = rocev2_env.Server.get_ipv4()

    # Start server in background
    server_proc = rocev2_env.Server.run(
        "ib_write_bw -d rxe_server -R -x 1 > /tmp/ib_write_bw_server.log 2>&1",
        background=True
    )

    time.sleep(2)  # Wait for server to be ready

    try:
        # Run client, redirect output to file
        rocev2_env.Client.run(
            f"ib_write_bw -d rxe_client -R -x 1 {server_ip} > /tmp/ib_write_bw_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Print server output
        rocev2_env.Server.run("cat /tmp/ib_write_bw_server.log")

        # Print client output
        rocev2_env.Client.run("cat /tmp/ib_write_bw_client.log")


@pytest.mark.skip(reason="ib_write_bw/rping IPv6 support has issues")
def test_ib_write_bw_ipv6(rocev2_env):
    """Test RDMA bandwidth over IPv6 using ib_write_bw"""
    server_ipv6 = rocev2_env.Server.get_ipv6()

    # Start server in background (use -g 2 for IPv6 GID index)
    server_proc = rocev2_env.Server.run(
        "ib_write_bw -d rxe_server -R -x 2 > /tmp/ib_write_bw_server_ipv6.log 2>&1",
        background=True
    )

    time.sleep(2)

    try:
        rocev2_env.Client.run(
            f"ib_write_bw -d rxe_client -R -x 2 {server_ipv6} > /tmp/ib_write_bw_client_ipv6.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Print server output
        rocev2_env.Server.run("cat /tmp/ib_write_bw_server_ipv6.log")

        # Print client output
        rocev2_env.Client.run("cat /tmp/ib_write_bw_client_ipv6.log")
