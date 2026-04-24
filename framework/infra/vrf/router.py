# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import subprocess
import uuid
from typing import Dict
from ...topo.router import RouterTopo
from ..base import BaseInfra, VrfNode


class VrfRouterInfra(RouterTopo, BaseInfra):
    """VRF-based Router topology"""
    
    class Client(RouterTopo.Client, VrfNode):
        def __init__(self, executor):
            self._name = "client"
            VrfNode.__init__(self, executor, self._name, "Client")

        def get_ipv4(self) -> str:
            return "10.0.1.2"

        def get_ipv6(self) -> str:
            return "2001:db8:1::2"

        def get_iface(self) -> str:
            return "veth_c"

    class Router(RouterTopo.Router, VrfNode):
        def __init__(self, executor):
            self._name = "router"
            VrfNode.__init__(self, executor, self._name, "Router")

        def get_ip_to_client(self) -> str:
            return "10.0.1.1"

        def get_ip_to_server(self) -> str:
            return "10.0.2.1"

        def get_iface_to_client(self) -> str:
            return "veth_rc"

        def get_iface_to_server(self) -> str:
            return "veth_rs"
    
    class Server(RouterTopo.Server, VrfNode):
        def __init__(self, executor):
            self._name = "server"
            VrfNode.__init__(self, executor, self._name, "Server")

        def get_ipv4(self) -> str:
            return "10.0.2.2"

        def get_ipv6(self) -> str:
            return "2001:db8:2::2"

        def get_iface(self) -> str:
            return "veth_s"

    def __init__(self):
        self.prefix = str(uuid.uuid4())[:8]
        self._logical_to_physical: Dict[str, str] = {}
        self._logical_to_table: Dict[str, int] = {}
        self._next_table = 100
        self.veths = []

        self.Client = self.Client(self)
        self.Router = self.Router(self)
        self.Server = self.Server(self)
    
    def setup(self) -> Dict[str, str]:
        client_name = "client"
        router_name = "router"
        server_name = "server"

        # Clean up potentially leftover old interfaces
        subprocess.run(f"ip link del {self.Client.get_iface()}", shell=True, stderr=subprocess.DEVNULL)
        subprocess.run(f"ip link del {self.Router.get_iface_to_server()}", shell=True, stderr=subprocess.DEVNULL)

        # Create VRF devices
        for logical_node in [client_name, router_name, server_name]:
            vrf_name = f"{self.prefix}_{logical_node}"
            table_id = self._next_table
            self._next_table += 1

            subprocess.run(f"ip link add {vrf_name} type vrf table {table_id}", shell=True, check=True)
            subprocess.run(f"ip link set {vrf_name} up", shell=True, check=True)
            self._logical_to_physical[logical_node] = vrf_name
            self._logical_to_table[logical_node] = table_id

        client_vrf = self._logical_to_physical[client_name]
        router_vrf = self._logical_to_physical[router_name]
        server_vrf = self._logical_to_physical[server_name]

        # Create veth pairs directly with final names (no rename needed)
        # Pair 1: client <-> router
        subprocess.run(f"ip link add {self.Client.get_iface()} type veth peer name {self.Router.get_iface_to_client()}", shell=True, check=True)

        subprocess.run(f"ip link set {self.Client.get_iface()} master {client_vrf}", shell=True, check=True)
        subprocess.run(f"ip link set {self.Router.get_iface_to_client()} master {router_vrf}", shell=True, check=True)
        subprocess.run(f"ip link set {self.Client.get_iface()} up", shell=True, check=True)
        subprocess.run(f"ip link set {self.Router.get_iface_to_client()} up", shell=True, check=True)

        # Pair 2: router <-> server
        subprocess.run(f"ip link add {self.Router.get_iface_to_server()} type veth peer name {self.Server.get_iface()}", shell=True, check=True)

        subprocess.run(f"ip link set {self.Router.get_iface_to_server()} master {router_vrf}", shell=True, check=True)
        subprocess.run(f"ip link set {self.Server.get_iface()} master {server_vrf}", shell=True, check=True)
        subprocess.run(f"ip link set {self.Router.get_iface_to_server()} up", shell=True, check=True)
        subprocess.run(f"ip link set {self.Server.get_iface()} up", shell=True, check=True)

        # Configure IP
        subprocess.run(f"ip addr add {self.Client.get_ipv4()}/24 dev {self.Client.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip addr add {self.Router.get_ip_to_client()}/24 dev {self.Router.get_iface_to_client()}", shell=True, check=True)
        subprocess.run(f"ip addr add {self.Router.get_ip_to_server()}/24 dev {self.Router.get_iface_to_server()}", shell=True, check=True)
        subprocess.run(f"ip addr add {self.Server.get_ipv4()}/24 dev {self.Server.get_iface()}", shell=True, check=True)

        # Enable IP forwarding on router
        subprocess.run(f"ip vrf exec {router_vrf} sysctl -w net.ipv4.ip_forward=1", shell=True, check=True)

        # Add default routes
        client_table = self._logical_to_table[client_name]
        server_table = self._logical_to_table[server_name]
        subprocess.run(f"ip route add default via {self.Router.get_ip_to_client()} dev {self.Client.get_iface()} table {client_table}", shell=True, check=True)
        subprocess.run(f"ip route add default via {self.Router.get_ip_to_server()} dev {self.Server.get_iface()} table {server_table}", shell=True, check=True)

        self.veths.extend([(self.Client.get_iface(), self.Router.get_iface_to_client()),
                           (self.Router.get_iface_to_server(), self.Server.get_iface())])

        return self._logical_to_physical.copy()
    
    def cleanup(self):
        for veth, peer in self.veths:
            subprocess.run(f"ip link del {veth}", shell=True, stderr=subprocess.DEVNULL)
        for vrf in self._logical_to_physical.values():
            subprocess.run(f"ip link del {vrf}", shell=True, stderr=subprocess.DEVNULL)
