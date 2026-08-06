# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import subprocess
import uuid
from typing import Dict
from ...topo.client_server import ClientServerTopo
from ...topo.node import Client, Server
from ..base import BaseInfra, NetnsNode


class NetnsClientServerInfra(ClientServerTopo, BaseInfra):
    """Netns-based Client-Server topology"""

    CLIENT_TAG = "Client"
    SERVER_TAG = "Server"

    class _ClientNode(Client, NetnsNode):
        def __init__(self, infra):
            NetnsNode.__init__(self, infra, infra.CLIENT_TAG)

        def get_ipv4(self) -> str:
            return "192.168.100.2"

        def get_ipv6(self) -> str:
            return "2001:db8::2"

        def get_iface(self) -> str:
            return "eth0"

    class _ServerNode(Server, NetnsNode):
        def __init__(self, infra):
            NetnsNode.__init__(self, infra, infra.SERVER_TAG)

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

        self._client = self._ClientNode(self)
        self._server = self._ServerNode(self)

    @property
    def Client(self) -> _ClientNode:
        return self._client

    @property
    def Server(self) -> _ServerNode:
        return self._server

    def setup(self) -> None:
        client_ipv4 = self._client.get_ipv4()
        client_ipv6 = self._client.get_ipv6()
        server_ipv4 = self._server.get_ipv4()
        server_ipv6 = self._server.get_ipv6()
        client_iface = self._client.get_iface()
        server_iface = self._server.get_iface()

        for logical_node in [self.CLIENT_TAG, self.SERVER_TAG]:
            physical_name = f"{self.prefix}_{logical_node}"
            subprocess.run(f"ip netns add {physical_name}", shell=True, check=True)
            self._logical_to_physical[logical_node] = physical_name

        client_ns = self._logical_to_physical[self.CLIENT_TAG]
        server_ns = self._logical_to_physical[self.SERVER_TAG]

        subprocess.run(
            f"ip netns exec {client_ns} ip link add {client_iface} type veth peer name {server_iface} netns {server_ns}",
            shell=True, check=True)
        self.veths.append((client_iface, server_iface))

        subprocess.run(f"ip netns exec {client_ns} ip addr add {client_ipv4}/24 dev {client_iface}", shell=True, check=True)

        subprocess.run(f"ip netns exec {server_ns} ip addr add {server_ipv4}/24 dev {server_iface}", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip addr add {server_ipv6}/64 dev {server_iface}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip addr add {client_ipv6}/64 dev {client_iface}", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip link set {server_iface} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip link set {client_iface} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip link set lo up", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip link set lo up", shell=True, check=True)

        self._health_check()

    def cleanup(self) -> None:
        for veth, peer in self.veths:
            subprocess.run(f"ip link del {veth}", shell=True, stderr=subprocess.DEVNULL)
        for physical_ns in self._logical_to_physical.values():
            subprocess.run(f"ip netns del {physical_ns}", shell=True, stderr=subprocess.DEVNULL)

    def _health_check(self):
        self._client._wait_for_ipv6_dad()
        self._server._wait_for_ipv6_dad()
        self._client.run(f"ping -c 1 -W 1 {self._server.get_ipv4()}")
        self._client.run(f"ping -c 1 -W 1 {self._server.get_ipv6()}")
