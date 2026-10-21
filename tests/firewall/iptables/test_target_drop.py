# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
"""iptables/ip6tables DROP rule tests.

Verify that a DROP rule for ICMP/ICMPv6 blocks traffic when applied on the
server INPUT chain and on the router FORWARD chain. Tests invoke the legacy
iptables/ip6tables binaries explicitly so ip_tables.ko/ip6_tables.ko is
exercised instead of nf_tables.
"""

import pytest
from framework.helpers import is_100_percent_loss


@pytest.mark.netfilter
def test_target_drop_icmp_client_server(client_server_env):
    """Verify iptables-legacy DROP on the server INPUT chain blocks ICMP.

    Adds an INPUT DROP rule for ICMP on the server, confirms the client's
    ping loses 100% of packets, then removes the rule.
    """
    infra = client_server_env
    infra.Client.run(f"ping -c 1 -W 1 {infra.Server.get_ipv4()}")

    infra.Server.run("iptables-legacy -A INPUT -p icmp -j DROP")
    result = infra.Client.run(f"ping -c 1 -W 1 {infra.Server.get_ipv4()}", expect="failed")

    assert is_100_percent_loss(result.stdout + result.stderr)
    infra.Server.run("iptables-legacy -D INPUT -p icmp -j DROP")


@pytest.mark.netfilter
def test_target_drop_icmp_router(router_env):
    """Verify iptables-legacy DROP on the router FORWARD chain blocks ICMP.

    Adds a FORWARD DROP rule for ICMP on the router, confirms the client's
    ping to the server loses 100% of packets, then removes the rule.
    """
    infra = router_env

    server_ipv4 = infra.Server.get_ipv4()
    infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}")

    infra.Router.run("iptables-legacy -A FORWARD -p icmp -j DROP")
    result = infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}", expect="failed")

    assert is_100_percent_loss(result.stdout + result.stderr)
    infra.Router.run("iptables-legacy -D FORWARD -p icmp -j DROP")


@pytest.mark.netfilter
def test_target_drop_icmpv6_client_server(client_server_env):
    """Verify ip6tables-legacy DROP on the server INPUT chain blocks ICMPv6.

    Adds an INPUT DROP rule for ICMPv6 on the server, confirms the client's
    IPv6 ping loses 100% of packets, then removes the rule.
    """
    infra = client_server_env
    server_ipv6 = infra.Server.get_ipv6()
    infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}")

    infra.Server.run("ip6tables-legacy -A INPUT -p ipv6-icmp -j DROP")
    result = infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}", expect="failed")

    assert is_100_percent_loss(result.stdout + result.stderr)
    infra.Server.run("ip6tables-legacy -D INPUT -p ipv6-icmp -j DROP")


@pytest.mark.netfilter
def test_target_drop_icmpv6_router(router_env):
    """Verify ip6tables-legacy DROP on the router FORWARD chain blocks ICMPv6.

    Adds a FORWARD DROP rule for ICMPv6 on the router, confirms the client's
    IPv6 ping to the server loses 100% of packets, then removes the rule.
    """
    infra = router_env
    server_ipv6 = infra.Server.get_ipv6()
    infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}")

    infra.Router.run("ip6tables-legacy -A FORWARD -p ipv6-icmp -j DROP")
    result = infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}", expect="failed")

    assert is_100_percent_loss(result.stdout + result.stderr)
    infra.Router.run("ip6tables-legacy -D FORWARD -p ipv6-icmp -j DROP")
