# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
"""iptables DROP rule tests.

Verify that an iptables DROP rule for ICMP blocks traffic when applied
on the server INPUT chain and on the router FORWARD chain.
"""

import pytest
from framework.helpers import is_100_percent_loss


@pytest.mark.netfilter
def test_drop_icmp_client_server(client_server_env):
    """Verify iptables DROP on the server INPUT chain blocks ICMP.

    Adds an INPUT DROP rule for ICMP on the server, confirms the client's
    ping loses 100% of packets, then removes the rule.
    """
    infra = client_server_env
    
    infra.Server.run("iptables -A INPUT -p icmp -j DROP")
    result = infra.Client.run(f"ping -c 3 -W 2 {infra.Server.get_ipv4()}", expect="failed")
    
    assert is_100_percent_loss(result.stdout + result.stderr)
    infra.Server.run("iptables -D INPUT -p icmp -j DROP")


@pytest.mark.netfilter
def test_drop_icmp_router(router_env):
    """Verify iptables DROP on the router FORWARD chain blocks ICMP.

    Adds a FORWARD DROP rule for ICMP on the router, confirms the client's
    ping to the server loses 100% of packets, then removes the rule.
    """
    infra = router_env
    
    server_ipv4 = infra.Server.get_ipv4()
    
    infra.Router.run("iptables -A FORWARD -p icmp -j DROP")
    result = infra.Client.run(f"ping -c 3 -W 2 {server_ipv4}", expect="failed")
    
    assert is_100_percent_loss(result.stdout + result.stderr)
    infra.Router.run("iptables -D FORWARD -p icmp -j DROP")
