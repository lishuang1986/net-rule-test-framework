# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
from framework.helpers import get_avg_rtt


@pytest.mark.tc
def test_tc_delay_client_server(client_server_env):
    infra = client_server_env
    
    iface = infra.Client.get_iface()
    infra.Client.run(f"tc qdisc add dev {iface} root netem delay 100ms")
    
    result = infra.Client.run(f"ping -c 5 -W 2 {infra.Server.get_ipv4()}")
    
    avg_rtt = get_avg_rtt(result.stdout)
    if avg_rtt > 0:
        assert avg_rtt >= 100
    
    infra.Client.run(f"tc qdisc del dev {iface} root")


@pytest.mark.tc
def test_tc_delay_on_router(router_env):
    infra = router_env
    
    iface = infra.Router.get_iface_to_server()
    infra.Router.run(f"tc qdisc add dev {iface} root netem delay 100ms")
    
    result = infra.Client.run(f"ping -c 5 -W 2 {infra.Server.get_ipv4()}")
    
    avg_rtt = get_avg_rtt(result.stdout)
    if avg_rtt > 0:
        assert avg_rtt >= 100
    
    infra.Router.run(f"tc qdisc del dev {iface} root")
