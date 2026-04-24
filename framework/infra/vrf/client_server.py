# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import subprocess
import uuid
from typing import Dict
from ...topo.client_server import ClientServerTopo
from ..base import BaseInfra, VrfNode


class VrfClientServerInfra(ClientServerTopo, BaseInfra):
    """VRF-based Client-Server topology"""
    
    class Client(ClientServerTopo.Client, VrfNode):
        def __init__(self, executor):
            self._name = "client"
            VrfNode.__init__(self, executor, self._name, "Client")

        def get_ipv4(self) -> str:
            return "10.0.0.2"

        def get_ipv6(self) -> str:
            return "2001:db8:10::2"

        def get_iface(self) -> str:
            return "veth_c"
    
    class Server(ClientServerTopo.Server, VrfNode):
        def __init__(self, executor):
            self._name = "server"
            VrfNode.__init__(self, executor, self._name, "Server")

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
        
        self.Client = self.Client(self)
        self.Server = self.Server(self)
    
    def setup(self) -> Dict[str, str]:
        client_name = "client"
        server_name = "server"
        client_iface = self.Client.get_iface()
        server_iface = self.Server.get_iface()

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
        subprocess.run(f"ip addr add {self.Client.get_ipv4()}/24 dev {client_iface}", shell=True, check=True)
        subprocess.run(f"ip addr add {self.Server.get_ipv4()}/24 dev {server_iface}", shell=True, check=True)

        self.veths.append((client_iface, server_iface))

        return self._logical_to_physical.copy()
    
    def cleanup(self):
        for veth, peer in self.veths:
            subprocess.run(f"ip link del {veth}", shell=True, stderr=subprocess.DEVNULL)
        for vrf in self._logical_to_physical.values():
            subprocess.run(f"ip link del {vrf}", shell=True, stderr=subprocess.DEVNULL)
