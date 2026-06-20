# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import subprocess
import uuid
from typing import Dict
from ...topo.router import RouterTopo
from ...topo.node import Client, Router, Server
from ..base import BaseInfra, NetnsNode


class NetnsRouterInfra(RouterTopo, BaseInfra):
    """Netns-based Router topology"""

    class _ClientNode(Client, NetnsNode):
        def __init__(self, infra):
            NetnsNode.__init__(self, infra, "client", "Client")

        def get_ipv4(self) -> str:
            return "192.168.1.2"

        def get_ipv6(self) -> str:
            return "2001:db8:1::2"

        def get_iface(self) -> str:
            return "eth0"

    class _RouterNode(Router, NetnsNode):
        def __init__(self, infra):
            NetnsNode.__init__(self, infra, "router", "Router")

        def get_ipv4_to_client(self) -> str:
            return "192.168.1.1"

        def get_ipv4_to_server(self) -> str:
            return "192.168.2.1"

        def get_ipv6_to_client(self) -> str:
            return "2001:db8:1::1"

        def get_ipv6_to_server(self) -> str:
            return "2001:db8:2::1"

        def get_iface_to_client(self) -> str:
            return "eth0"

        def get_iface_to_server(self) -> str:
            return "eth1"

    class _ServerNode(Server, NetnsNode):
        def __init__(self, infra):
            NetnsNode.__init__(self, infra, "server", "Server")

        def get_ipv4(self) -> str:
            return "192.168.2.2"

        def get_ipv6(self) -> str:
            return "2001:db8:2::2"

        def get_iface(self) -> str:
            return "eth0"

    def __init__(self):
        self.prefix = str(uuid.uuid4())[:8]
        self._logical_to_physical: Dict[str, str] = {}
        self.veths = []

        self._client = self._ClientNode(self)
        self._router = self._RouterNode(self)
        self._server = self._ServerNode(self)

    @property
    def Client(self) -> _ClientNode:
        return self._client

    @property
    def Router(self) -> _RouterNode:
        return self._router

    @property
    def Server(self) -> _ServerNode:
        return self._server

    def setup(self) -> None:
        client_name = "client"
        router_name = "router"
        server_name = "server"

        for logical_node in [client_name, router_name, server_name]:
            physical_name = f"{self.prefix}_{logical_node}"
            subprocess.run(f"ip netns add {physical_name}", shell=True, check=True)
            self._logical_to_physical[logical_node] = physical_name

        self._create_veth(client_name, router_name,
                          self._client.get_iface(), self._router.get_iface_to_client())
        self._create_veth(router_name, server_name,
                          self._router.get_iface_to_server(), self._server.get_iface())

        client_ns = self._logical_to_physical[client_name]
        router_ns = self._logical_to_physical[router_name]
        server_ns = self._logical_to_physical[server_name]

        subprocess.run(f"ip netns exec {client_ns} ip addr add {self._client.get_ipv4()}/24 dev {self._client.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip -6 addr add {self._client.get_ipv6()}/64 dev {self._client.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip link set {self._client.get_iface()} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip link set lo up", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip route add default via {self._router.get_ipv4_to_client()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip -6 route add default via {self._router.get_ipv6_to_client()}", shell=True, check=True)

        subprocess.run(f"ip netns exec {router_ns} ip addr add {self._router.get_ipv4_to_client()}/24 dev {self._router.get_iface_to_client()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} ip -6 addr add {self._router.get_ipv6_to_client()}/64 dev {self._router.get_iface_to_client()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} ip link set {self._router.get_iface_to_client()} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} ip addr add {self._router.get_ipv4_to_server()}/24 dev {self._router.get_iface_to_server()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} ip -6 addr add {self._router.get_ipv6_to_server()}/64 dev {self._router.get_iface_to_server()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} ip link set {self._router.get_iface_to_server()} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} ip link set lo up", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} sysctl -w net.ipv4.ip_forward=1", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} sysctl -w net.ipv6.conf.all.forwarding=1", shell=True, check=True)

        subprocess.run(f"ip netns exec {server_ns} ip addr add {self._server.get_ipv4()}/24 dev {self._server.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip -6 addr add {self._server.get_ipv6()}/64 dev {self._server.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip link set {self._server.get_iface()} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip link set lo up", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip route add default via {self._router.get_ipv4_to_server()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip -6 route add default via {self._router.get_ipv6_to_server()}", shell=True, check=True)

        self._health_check()

    def _health_check(self):
        self._client._wait_for_ipv6_dad()
        self._router._wait_for_ipv6_dad()
        self._server._wait_for_ipv6_dad()
        self._client.run(f"ping -c 1 -W 1 {self._server.get_ipv4()}")
        self._client.run(f"ping -c 1 -W 1 {self._server.get_ipv6()}")

    def cleanup(self) -> None:
        for veth, peer in self.veths:
            subprocess.run(f"ip link del {veth}", shell=True, stderr=subprocess.DEVNULL)
        for physical_ns in self._logical_to_physical.values():
            subprocess.run(f"ip netns del {physical_ns}", shell=True, stderr=subprocess.DEVNULL)

    def _create_veth(self, node_a: str, node_b: str, iface_a: str, iface_b: str):
        phys_a = self._logical_to_physical[node_a]
        phys_b = self._logical_to_physical[node_b]

        subprocess.run(
            f"ip netns exec {phys_a} ip link add {iface_a} type veth peer name {iface_b} netns {phys_b}",
            shell=True, check=True)

        self.veths.append((iface_a, iface_b))
