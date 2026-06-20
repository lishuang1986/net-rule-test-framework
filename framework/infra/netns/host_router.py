# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import shutil
import subprocess
import uuid
import time
from typing import Dict
from ...topo.router import RouterTopo
from ...topo.node import Client, Router, Server
from ..base import BaseInfra, HostNode, NetnsNode


class NetnsHostRouterInfra(RouterTopo, BaseInfra):
    """Router topology with router on host (netns 0) and client/server in netns"""

    class _ClientNode(Client, NetnsNode):
        def __init__(self, infra):
            NetnsNode.__init__(self, infra, "client", "Client")

        def get_ipv4(self) -> str:
            return "192.168.1.2"

        def get_ipv6(self) -> str:
            return "2001:db8:1::2"

        def get_iface(self) -> str:
            return "eth0"

    class _RouterNode(Router, HostNode):
        def __init__(self, infra):
            HostNode.__init__(self, infra, "router", "Router")

        def get_ipv4_to_client(self) -> str:
            return "192.168.1.1"

        def get_ipv4_to_server(self) -> str:
            return "192.168.2.1"

        def get_ipv6_to_client(self) -> str:
            return "2001:db8:1::1"

        def get_ipv6_to_server(self) -> str:
            return "2001:db8:2::1"

        def get_iface_to_client(self) -> str:
            return "r2c"

        def get_iface_to_server(self) -> str:
            return "r2s"

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
        self._firewalld_was_enabled = False

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
        # Stop firewalld if it is enabled, to avoid interference with tests
        if shutil.which("systemctl") is not None:
            ret = subprocess.run(["systemctl", "is-enabled", "firewalld"],
                                 capture_output=True, text=True)
            self._firewalld_was_enabled = ret.returncode == 0
            if self._firewalld_was_enabled:
                subprocess.run(["systemctl", "stop", "firewalld"], check=True)

        client_name = "client"
        server_name = "server"

        # Only create client and server netns (no router netns)
        for logical_node in [client_name, server_name]:
            physical_name = f"{self.prefix}_{logical_node}"
            subprocess.run(f"ip netns add {physical_name}", shell=True, check=True)
            self._logical_to_physical[logical_node] = physical_name

        # Create veth from host: host side = r2c, peer in client ns = eth0
        self._create_veth_to_host(client_name,
                                  self._router.get_iface_to_client(),
                                  self._client.get_iface())
        # Create veth from host: host side = r2s, peer in server ns = eth0
        self._create_veth_to_host(server_name,
                                  self._router.get_iface_to_server(),
                                  self._server.get_iface())

        client_ns = self._logical_to_physical[client_name]
        server_ns = self._logical_to_physical[server_name]

        # Configure client
        subprocess.run(f"ip netns exec {client_ns} ip link set {self._client.get_iface()} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip link set lo up", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip addr add {self._client.get_ipv4()}/24 dev {self._client.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip -6 addr add {self._client.get_ipv6()}/64 dev {self._client.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip route add default via {self._router.get_ipv4_to_client()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip -6 route add default via {self._router.get_ipv6_to_client()}", shell=True, check=True)

        # Configure router (on host)
        subprocess.run(f"ip link set {self._router.get_iface_to_client()} up", shell=True, check=True)
        subprocess.run(f"ip addr add {self._router.get_ipv4_to_client()}/24 dev {self._router.get_iface_to_client()}", shell=True, check=True)
        subprocess.run(f"ip -6 addr add {self._router.get_ipv6_to_client()}/64 dev {self._router.get_iface_to_client()}", shell=True, check=True)
        subprocess.run(f"ip link set {self._router.get_iface_to_server()} up", shell=True, check=True)
        subprocess.run(f"ip addr add {self._router.get_ipv4_to_server()}/24 dev {self._router.get_iface_to_server()}", shell=True, check=True)
        subprocess.run(f"ip -6 addr add {self._router.get_ipv6_to_server()}/64 dev {self._router.get_iface_to_server()}", shell=True, check=True)
        subprocess.run(f"sysctl -w net.ipv4.ip_forward=1", shell=True, check=True)
        subprocess.run(f"sysctl -w net.ipv6.conf.all.forwarding=1", shell=True, check=True)

        # Configure server
        subprocess.run(f"ip netns exec {server_ns} ip link set {self._server.get_iface()} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip link set lo up", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip addr add {self._server.get_ipv4()}/24 dev {self._server.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip -6 addr add {self._server.get_ipv6()}/64 dev {self._server.get_iface()}", shell=True, check=True)
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
        for veth in self.veths:
            subprocess.run(f"ip link del {veth}", shell=True, stderr=subprocess.DEVNULL)
        for physical_ns in self._logical_to_physical.values():
            subprocess.run(f"ip netns del {physical_ns}", shell=True, stderr=subprocess.DEVNULL)
        if self._firewalld_was_enabled:
            subprocess.run(["systemctl", "start", "firewalld"], check=True)
            while subprocess.run(["firewall-cmd", "--state"],
                                  capture_output=True, text=True).stdout.strip() != "running":
                time.sleep(1)

    def _create_veth_to_host(self, node: str, host_iface: str, peer_iface: str):
        """Create veth between host and a netns node"""
        phys = self._logical_to_physical[node]

        # Create from host: host side = host_iface, peer in netns = peer_iface
        subprocess.run(
            f"ip link add {host_iface} type veth peer name {peer_iface} netns {phys}",
            shell=True, check=True)

        self.veths.append(host_iface)
