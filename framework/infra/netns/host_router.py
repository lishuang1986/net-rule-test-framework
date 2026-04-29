# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import subprocess
import uuid
from typing import Dict
from ...topo.router import RouterTopo
from ..base import BaseInfra, HostNode, NetnsNode


class NetnsHostRouterInfra(RouterTopo, BaseInfra):
    """Router topology with router on host (netns 0) and client/server in netns"""

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

    class Router(RouterTopo.Router, HostNode):
        def __init__(self, executor):
            self._name = "router"
            HostNode.__init__(self, executor, self._name, "Router")

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
        self._firewalld_was_enabled = False

        self.Client = self.Client(self)
        self.Router = self.Router(self)
        self.Server = self.Server(self)

    def setup(self) -> Dict[str, str]:
        # Stop firewalld if it is enabled, to avoid interference with tests
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
                                  self.Router.get_iface_to_client(),
                                  self.Client.get_iface())
        # Create veth from host: host side = r2s, peer in server ns = eth0
        self._create_veth_to_host(server_name,
                                  self.Router.get_iface_to_server(),
                                  self.Server.get_iface())

        client_ns = self._logical_to_physical[client_name]
        server_ns = self._logical_to_physical[server_name]

        # Configure client
        subprocess.run(f"ip netns exec {client_ns} ip link set {self.Client.get_iface()} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip link set lo up", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip addr add {self.Client.get_ipv4()}/24 dev {self.Client.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip -6 addr add {self.Client.get_ipv6()}/64 dev {self.Client.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip route add default via {self.Router.get_ipv4_to_client()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {client_ns} ip -6 route add default via {self.Router.get_ipv6_to_client()}", shell=True, check=True)

        # Configure router (on host)
        subprocess.run(f"ip link set {self.Router.get_iface_to_client()} up", shell=True, check=True)
        subprocess.run(f"ip addr add {self.Router.get_ipv4_to_client()}/24 dev {self.Router.get_iface_to_client()}", shell=True, check=True)
        subprocess.run(f"ip -6 addr add {self.Router.get_ipv6_to_client()}/64 dev {self.Router.get_iface_to_client()}", shell=True, check=True)
        subprocess.run(f"ip link set {self.Router.get_iface_to_server()} up", shell=True, check=True)
        subprocess.run(f"ip addr add {self.Router.get_ipv4_to_server()}/24 dev {self.Router.get_iface_to_server()}", shell=True, check=True)
        subprocess.run(f"ip -6 addr add {self.Router.get_ipv6_to_server()}/64 dev {self.Router.get_iface_to_server()}", shell=True, check=True)
        subprocess.run(f"sysctl -w net.ipv4.ip_forward=1", shell=True, check=True)
        subprocess.run(f"sysctl -w net.ipv6.conf.all.forwarding=1", shell=True, check=True)

        # Configure server
        subprocess.run(f"ip netns exec {server_ns} ip link set {self.Server.get_iface()} up", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip link set lo up", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip addr add {self.Server.get_ipv4()}/24 dev {self.Server.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip -6 addr add {self.Server.get_ipv6()}/64 dev {self.Server.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip route add default via {self.Router.get_ipv4_to_server()}", shell=True, check=True)
        subprocess.run(f"ip netns exec {server_ns} ip -6 route add default via {self.Router.get_ipv6_to_server()}", shell=True, check=True)

        self._health_check()
        return self._logical_to_physical.copy()

    def _health_check(self):
        self.Client._wait_for_ipv6_dad()
        self.Router._wait_for_ipv6_dad()
        self.Server._wait_for_ipv6_dad()
        self.Client.run(f"ping -c 1 -W 1 {self.Server.get_ipv4()}")
        self.Client.run(f"ping -c 1 -W 1 {self.Server.get_ipv6()}")

    def cleanup(self):
        for veth in self.veths:
            subprocess.run(f"ip link del {veth}", shell=True, stderr=subprocess.DEVNULL)
        for physical_ns in self._logical_to_physical.values():
            subprocess.run(f"ip netns del {physical_ns}", shell=True, stderr=subprocess.DEVNULL)
        if self._firewalld_was_enabled:
            subprocess.run(["systemctl", "start", "firewalld"], check=True)

    def _create_veth_to_host(self, node: str, host_iface: str, peer_iface: str):
        """Create veth between host and a netns node"""
        phys = self._logical_to_physical[node]

        # Create from host: host side = host_iface, peer in netns = peer_iface
        subprocess.run(
            f"ip link add {host_iface} type veth peer name {peer_iface} netns {phys}",
            shell=True, check=True)

        self.veths.append(host_iface)
