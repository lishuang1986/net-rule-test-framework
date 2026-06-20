# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import subprocess
import uuid
from typing import Dict
from ...topo.client_server import ClientServerTopo
from ...topo.node import Client, Server
from ..base import BaseInfra, VrfNode


class VrfClientServerInfra(ClientServerTopo, BaseInfra):
    """VRF-based Client-Server topology"""

    class _ClientNode(Client, VrfNode):
        def __init__(self, infra):
            VrfNode.__init__(self, infra, "client", "Client")

        def get_ipv4(self) -> str:
            return "10.0.0.2"

        def get_ipv6(self) -> str:
            return "2001:db8:10::2"

        def get_iface(self) -> str:
            return "veth_c"

    class _ServerNode(Server, VrfNode):
        def __init__(self, infra):
            VrfNode.__init__(self, infra, "server", "Server")

        def get_ipv4(self) -> str:
            return "10.0.0.1"

        def get_ipv6(self) -> str:
            return "2001:db8:10::1"

        def get_iface(self) -> str:
            return "veth_s"

    def __init__(self):
        self.prefix = str(uuid.uuid4())[:8]
        self._logical_to_physical: Dict[str, str] = {}
        self._next_table = 100
        self.veths = []
        self._selinux_mode = ""

        self._client = self._ClientNode(self)
        self._server = self._ServerNode(self)

    @property
    def Client(self) -> _ClientNode:
        return self._client

    @property
    def Server(self) -> _ServerNode:
        return self._server

    def setup(self) -> None:
        client_name = "client"
        server_name = "server"
        client_iface = self._client.get_iface()
        server_iface = self._server.get_iface()

        # Clean up potentially leftover old interfaces
        subprocess.run(f"ip link del {client_iface}", shell=True, stderr=subprocess.DEVNULL)

        # Create VRF devices
        for logical_node in [client_name, server_name]:
            vrf_name = f"{self.prefix}_{logical_node}"
            table_id = self._next_table
            self._next_table += 1

            subprocess.run(f"ip link add {vrf_name} type vrf table {table_id}", shell=True, check=True)
            subprocess.run(f"ip link set {vrf_name} up", shell=True, check=True)
            self._logical_to_physical[logical_node] = vrf_name

        client_vrf = self._logical_to_physical[client_name]
        server_vrf = self._logical_to_physical[server_name]

        # Create veth pairs directly with final names (no rename needed)
        subprocess.run(f"ip link add {client_iface} type veth peer name {server_iface}", shell=True, check=True)

        subprocess.run(f"ip link set {client_iface} master {client_vrf}", shell=True, check=True)
        subprocess.run(f"ip link set {server_iface} master {server_vrf}", shell=True, check=True)
        subprocess.run(f"ip link set {client_iface} up", shell=True, check=True)
        subprocess.run(f"ip link set {server_iface} up", shell=True, check=True)

        # Configure IP
        subprocess.run(f"ip addr add {self._client.get_ipv4()}/24 dev {client_iface}", shell=True, check=True)
        subprocess.run(f"ip addr add {self._server.get_ipv4()}/24 dev {server_iface}", shell=True, check=True)
        subprocess.run(f"ip addr add {self._client.get_ipv6()}/64 dev {client_iface}", shell=True, check=True)
        subprocess.run(f"ip addr add {self._server.get_ipv6()}/64 dev {server_iface}", shell=True, check=True)

        self.veths.append((client_iface, server_iface))

        result = subprocess.run("getenforce", shell=True, capture_output=True, text=True)
        self._selinux_mode = result.stdout.strip()
        if self._selinux_mode == "Enforcing":
            subprocess.run("setenforce 0", shell=True, check=True)

        self._health_check()

    def _health_check(self):
        self._client._wait_for_ipv6_dad()
        self._server._wait_for_ipv6_dad()
        self._client.run(f"ping -c 1 -W 1 {self._server.get_ipv4()}")
        self._client.run(f"ping -c 1 -W 1 {self._server.get_ipv6()}")

    def cleanup(self) -> None:
        if self._selinux_mode == "Enforcing":
            subprocess.run("setenforce 1", shell=True, stderr=subprocess.DEVNULL)
        for veth, peer in self.veths:
            subprocess.run(f"ip link del {veth}", shell=True, stderr=subprocess.DEVNULL)
        for vrf in self._logical_to_physical.values():
            subprocess.run(f"ip link del {vrf}", shell=True, stderr=subprocess.DEVNULL)
