# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import subprocess
import uuid
from typing import Dict
from ...topo.client_server import ClientServerTopo
from ..base import BaseInfra, NetnsNode


class NetnsClientServerInfra(ClientServerTopo, BaseInfra):
    """Netns-based Client-Server topology"""

    # Concrete implementation of Client node
    class Client(ClientServerTopo.Client, NetnsNode):
        def __init__(self, executor):
            self._name = "client"
            NetnsNode.__init__(self, executor, self._name, "Client")

        def get_ipv4(self) -> str:
            return "192.168.100.2"

        def get_ipv6(self) -> str:
            return "2001:db8::2"

        def get_iface(self) -> str:
            return "eth0"

    # Concrete implementation of Server node
    class Server(ClientServerTopo.Server, NetnsNode):
        def __init__(self, executor):
            self._name = "server"
            NetnsNode.__init__(self, executor, self._name, "Server")

        def get_ipv4(self) -> str:
            return "192.168.100.1"

        def get_ipv6(self) -> str:
            return "2001:db8::1"

        def get_iface(self) -> str:
            return "eth0"

    def __init__(self):
        self.prefix = str(uuid.uuid4())[:8]
        self._logical_to_physical: Dict[str, str] = {}
        self.veths = []

        # Instantiate node objects, passing self as executor
        self.Client = self.Client(self)
        self.Server = self.Server(self)

    def setup(self) -> Dict[str, str]:
        client_name = "client"
        server_name = "server"
        client_ipv4 = self.Client.get_ipv4()
        client_ipv6 = self.Client.get_ipv6()
        server_ipv4 = self.Server.get_ipv4()
        server_ipv6 = self.Server.get_ipv6()
        client_iface = self.Client.get_iface()
        server_iface = self.Server.get_iface()

        for logical_node in [client_name, server_name]:
            physical_name = f"{self.prefix}_{logical_node}"
            subprocess.run(f"ip netns add {physical_name}", shell=True, check=True)
            self._logical_to_physical[logical_node] = physical_name

        self._create_veth(client_name, server_name, client_iface, server_iface)

        client_ns = self._logical_to_physical[client_name]
        server_ns = self._logical_to_physical[server_name]

        subprocess.run(f"ip netns exec {client_ns} ip addr add {client_ipv4}/24 dev {client_iface}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip addr add {client_ipv6}/64 dev {client_iface}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip link set {client_iface} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip link set lo up", shell=True, check=True)

        subprocess.run(f"ip netns exec {server_ns} ip addr add {server_ipv4}/24 dev {server_iface}", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip addr add {server_ipv6}/64 dev {server_iface}", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip link set {server_iface} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip link set lo up", shell=True, check=True)

        self._health_check()
        return self._logical_to_physical.copy()

    def _health_check(self):
        self.Client._wait_for_ipv6_dad()
        self.Server._wait_for_ipv6_dad()
        self.Client.run(f"ping -c 1 -W 1 {self.Server.get_ipv4()}")
        self.Client.run(f"ping -c 1 -W 1 {self.Server.get_ipv6()}")

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
