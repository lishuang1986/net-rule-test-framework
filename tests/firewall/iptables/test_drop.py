# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
from framework.helpers import is_100_percent_loss


@pytest.mark.netfilter
def test_drop_icmp_client_server(client_server_env):
    infra = client_server_env
    
    infra.Server.run("iptables -A INPUT -p icmp -j DROP")
    result = infra.Client.run(f"ping -c 3 -W 2 {infra.Server.get_ipv4()}", expect="failed")
    
    assert is_100_percent_loss(result.stdout + result.stderr)
    infra.Server.run("iptables -D INPUT -p icmp -j DROP")


@pytest.mark.netfilter
def test_drop_icmp_router(router_env):
    infra = router_env
    
    server_ipv4 = infra.Server.get_ipv4()
    
    infra.Router.run("iptables -A FORWARD -p icmp -j DROP")
    result = infra.Client.run(f"ping -c 3 -W 2 {server_ipv4}", expect="failed")
    
    assert is_100_percent_loss(result.stdout + result.stderr)
    infra.Router.run("iptables -D FORWARD -p icmp -j DROP")
