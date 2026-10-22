# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
"""iptables/ip6tables DROP rule tests.

Verify that a DROP rule for ICMP/ICMPv6 blocks traffic when applied on the
server INPUT/OUTPUT chains and on the router FORWARD/PREROUTING/POSTROUTING
chains. Tests invoke the legacy iptables/ip6tables binaries explicitly so
ip_tables.ko/ip6_tables.ko is exercised instead of nf_tables.
"""

import pytest
from framework.helpers import is_100_percent_loss


@pytest.mark.netfilter
def test_target_drop_icmp_client_server(client_server_env):
    """Verify iptables-legacy DROP on the server INPUT/OUTPUT chains blocks ICMP.

    Adds INPUT and OUTPUT DROP rules for ICMP on the server, confirms the
    client's ping loses 100% of packets, then removes the rules.
    """
    infra = client_server_env

    try:
        # INPUT test
        infra.Client.run(f"ping -c 1 -W 1 {infra.Server.get_ipv4()}")

        infra.Server.run("iptables-legacy -A INPUT -p icmp -j DROP")
        result = infra.Client.run(f"ping -c 1 -W 1 {infra.Server.get_ipv4()}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Server.run("iptables-legacy -D INPUT -p icmp -j DROP")

        # OUTPUT test
        infra.Client.run(f"ping -c 1 -W 1 {infra.Server.get_ipv4()}")

        infra.Server.run("iptables-legacy -A OUTPUT -p icmp -j DROP")
        result = infra.Client.run(f"ping -c 1 -W 1 {infra.Server.get_ipv4()}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Server.run("iptables-legacy -D OUTPUT -p icmp -j DROP")
    finally:
        infra.Server.run("iptables-legacy -D INPUT -p icmp -j DROP", check=False)
        infra.Server.run("iptables-legacy -D OUTPUT -p icmp -j DROP", check=False)


@pytest.mark.netfilter
def test_target_drop_icmp_router(router_env):
    """Verify iptables-legacy DROP on the router FORWARD/routing chains.

    The filter table has no PREROUTING/POSTROUTING chains, so the mangle table
    is used for those. Adds DROP rules for ICMP on the router's FORWARD,
    PREROUTING and POSTROUTING chains in turn, confirms the client's ping to
    the server loses 100% of packets each time, then removes the rule.
    """
    infra = router_env

    server_ipv4 = infra.Server.get_ipv4()

    try:
        # FORWARD test
        infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}")

        infra.Router.run("iptables-legacy -A FORWARD -p icmp -j DROP")
        result = infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Router.run("iptables-legacy -D FORWARD -p icmp -j DROP")

        # PREROUTING test
        infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}")

        infra.Router.run("iptables-legacy -t mangle -A PREROUTING -p icmp -j DROP")
        result = infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Router.run("iptables-legacy -t mangle -D PREROUTING -p icmp -j DROP")

        # POSTROUTING test
        infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}")

        infra.Router.run("iptables-legacy -t mangle -A POSTROUTING -p icmp -j DROP")
        result = infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Router.run("iptables-legacy -t mangle -D POSTROUTING -p icmp -j DROP")
    finally:
        infra.Router.run("iptables-legacy -D FORWARD -p icmp -j DROP", check=False)
        infra.Router.run("iptables-legacy -t mangle -D PREROUTING -p icmp -j DROP", check=False)
        infra.Router.run("iptables-legacy -t mangle -D POSTROUTING -p icmp -j DROP", check=False)


@pytest.mark.netfilter
def test_target_drop_icmpv6_client_server(client_server_env):
    """Verify ip6tables-legacy DROP on the server INPUT/OUTPUT chains blocks ICMPv6.

    Adds INPUT and OUTPUT DROP rules for ICMPv6 on the server, confirms the
    client's IPv6 ping loses 100% of packets, then removes the rules.
    """
    infra = client_server_env
    server_ipv6 = infra.Server.get_ipv6()

    try:
        # INPUT test
        infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}")

        infra.Server.run("ip6tables-legacy -A INPUT -p ipv6-icmp -j DROP")
        result = infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Server.run("ip6tables-legacy -D INPUT -p ipv6-icmp -j DROP")

        # OUTPUT test
        infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}")

        infra.Server.run("ip6tables-legacy -A OUTPUT -p ipv6-icmp -j DROP")
        result = infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Server.run("ip6tables-legacy -D OUTPUT -p ipv6-icmp -j DROP")
    finally:
        infra.Server.run("ip6tables-legacy -D INPUT -p ipv6-icmp -j DROP", check=False)
        infra.Server.run("ip6tables-legacy -D OUTPUT -p ipv6-icmp -j DROP", check=False)


@pytest.mark.netfilter
def test_target_drop_icmpv6_router(router_env):
    """Verify ip6tables-legacy DROP on the router FORWARD/routing chains.

    The filter table has no PREROUTING/POSTROUTING chains, so the mangle table
    is used for those. Adds DROP rules for ICMPv6 on the router's FORWARD,
    PREROUTING and POSTROUTING chains in turn, confirms the client's IPv6 ping
    to the server loses 100% of packets each time, then removes the rule.
    """
    infra = router_env
    server_ipv6 = infra.Server.get_ipv6()

    try:
        # FORWARD test
        infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}")

        infra.Router.run("ip6tables-legacy -A FORWARD -p ipv6-icmp -j DROP")
        result = infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Router.run("ip6tables-legacy -D FORWARD -p ipv6-icmp -j DROP")

        # PREROUTING test
        infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}")

        infra.Router.run("ip6tables-legacy -t mangle -A PREROUTING -p ipv6-icmp -j DROP")
        result = infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Router.run("ip6tables-legacy -t mangle -D PREROUTING -p ipv6-icmp -j DROP")

        # POSTROUTING test
        infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}")

        infra.Router.run("ip6tables-legacy -t mangle -A POSTROUTING -p ipv6-icmp -j DROP")
        result = infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Router.run("ip6tables-legacy -t mangle -D POSTROUTING -p ipv6-icmp -j DROP")
    finally:
        infra.Router.run("ip6tables-legacy -D FORWARD -p ipv6-icmp -j DROP", check=False)
        infra.Router.run("ip6tables-legacy -t mangle -D PREROUTING -p ipv6-icmp -j DROP", check=False)
        infra.Router.run("ip6tables-legacy -t mangle -D POSTROUTING -p ipv6-icmp -j DROP", check=False)
