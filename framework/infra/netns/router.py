# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import subprocess
import uuid
from typing import Dict
from ...topo.router import RouterTopo
from ..base import BaseInfra, NetnsNode


class NetnsRouterInfra(RouterTopo, BaseInfra):
    """Netns-based Router topology"""

    class Client(RouterTopo.Client, NetnsNode):
        def __init__(self, executor):
            self._name = "client"
            NetnsNode.__init__(self, executor, self._name, "Client")

        def get_ipv4(self) -> str:
            return "192.168.1.2"

        def get_ipv6(self) -> str:
            return "2001:db8:1::2"

        def get_iface(self) -> str:
            return "eth0"

    class Router(RouterTopo.Router, NetnsNode):
        def __init__(self, executor):
            self._name = "router"
            NetnsNode.__init__(self, executor, self._name, "Router")

        def get_ip_to_client(self) -> str:
            return "192.168.1.1"

        def get_ip_to_server(self) -> str:
            return "192.168.2.1"

        def get_iface_to_client(self) -> str:
            return "eth0"

        def get_iface_to_server(self) -> str:
            return "eth1"

    class Server(RouterTopo.Server, NetnsNode):
        def __init__(self, executor):
            self._name = "server"
            NetnsNode.__init__(self, executor, self._name, "Server")

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

        self.Client = self.Client(self)
        self.Router = self.Router(self)
        self.Server = self.Server(self)

    def setup(self) -> Dict[str, str]:
        client_name = "client"
        router_name = "router"
        server_name = "server"

        for logical_node in [client_name, router_name, server_name]:
            physical_name = f"{self.prefix}_{logical_node}"
            subprocess.run(f"ip netns add {physical_name}", shell=True, check=True)
            self._logical_to_physical[logical_node] = physical_name

        self._create_veth(client_name, router_name,
                          self.Client.get_iface(), self.Router.get_iface_to_client())
        self._create_veth(router_name, server_name,
                          self.Router.get_iface_to_server(), self.Server.get_iface())

        client_ns = self._logical_to_physical[client_name]
        router_ns = self._logical_to_physical[router_name]
        server_ns = self._logical_to_physical[server_name]

        subprocess.run(f"ip netns exec {client_ns} ip addr add {self.Client.get_ipv4()}/24 dev {self.Client.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip link set {self.Client.get_iface()} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip link set lo up", shell=True, check=True)

        subprocess.run(f"ip netns exec {router_ns} ip addr add {self.Router.get_ip_to_client()}/24 dev {self.Router.get_iface_to_client()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} ip link set {self.Router.get_iface_to_client()} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} ip addr add {self.Router.get_ip_to_server()}/24 dev {self.Router.get_iface_to_server()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} ip link set {self.Router.get_iface_to_server()} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} ip link set lo up", shell=True, check=True)
        subprocess.run(f"ip netns exec {router_ns} sysctl -w net.ipv4.ip_forward=1", shell=True, check=True)

        subprocess.run(f"ip netns exec {server_ns} ip addr add {self.Server.get_ipv4()}/24 dev {self.Server.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip link set {self.Server.get_iface()} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip link set lo up", shell=True, check=True)

        return self._logical_to_physical.copy()

    def cleanup(self):
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
