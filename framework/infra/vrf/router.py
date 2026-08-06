# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import shutil
import subprocess
import uuid
import time
from typing import Dict
from ...topo.router import RouterTopo
from ...topo.node import Client, Router, Server
from ..base import BaseInfra, VrfNode


class VrfRouterInfra(RouterTopo, BaseInfra):
    """VRF-based Router topology"""

    CLIENT_TAG = "Client"
    ROUTER_TAG = "Router"
    SERVER_TAG = "Server"

    class _ClientNode(Client, VrfNode):
        def __init__(self, infra):
            VrfNode.__init__(self, infra, infra.CLIENT_TAG)

        def get_ipv4(self) -> str:
            return "10.0.1.2"

        def get_ipv6(self) -> str:
            return "2001:db8:1::2"

        def get_iface(self) -> str:
            return "veth_c"

    class _RouterNode(Router, VrfNode):
        def __init__(self, infra):
            VrfNode.__init__(self, infra, infra.ROUTER_TAG)

        def get_ipv4_to_client(self) -> str:
            return "10.0.1.1"

        def get_ipv4_to_server(self) -> str:
            return "10.0.2.1"

        def get_ipv6_to_client(self) -> str:
            return "2001:db8:1::1"

        def get_ipv6_to_server(self) -> str:
            return "2001:db8:2::1"

        def get_iface_to_client(self) -> str:
            return "veth_rc"

        def get_iface_to_server(self) -> str:
            return "veth_rs"

    class _ServerNode(Server, VrfNode):
        def __init__(self, infra):
            VrfNode.__init__(self, infra, infra.SERVER_TAG)

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
        self._firewalld_was_enabled = False
        self._selinux_mode = ""

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

        result = subprocess.run("getenforce", shell=True, capture_output=True, text=True)
        self._selinux_mode = result.stdout.strip()
        if self._selinux_mode == "Enforcing":
            subprocess.run("setenforce 0", shell=True, check=True)

        # Clean up potentially leftover old interfaces
        subprocess.run(f"ip link del {self._client.get_iface()}", shell=True, stderr=subprocess.DEVNULL)
        subprocess.run(f"ip link del {self._router.get_iface_to_server()}", shell=True, stderr=subprocess.DEVNULL)

        # Create VRF devices
        for logical_node in [self.CLIENT_TAG, self.ROUTER_TAG, self.SERVER_TAG]:
            vrf_name = f"{self.prefix}_{logical_node}"
            table_id = self._next_table
            self._next_table += 1

            subprocess.run(f"ip link add {vrf_name} type vrf table {table_id}", shell=True, check=True)
            subprocess.run(f"ip link set {vrf_name} up", shell=True, check=True)
            self._logical_to_physical[logical_node] = vrf_name
            self._logical_to_table[logical_node] = table_id

        client_vrf = self._logical_to_physical[self.CLIENT_TAG]
        router_vrf = self._logical_to_physical[self.ROUTER_TAG]
        server_vrf = self._logical_to_physical[self.SERVER_TAG]

        # Create veth pairs directly with final names (no rename needed)
        # Pair 1: client <-> router
        subprocess.run(f"ip link add {self._client.get_iface()} type veth peer name {self._router.get_iface_to_client()}", shell=True, check=True)

        subprocess.run(f"ip link set {self._client.get_iface()} master {client_vrf}", shell=True, check=True)
        subprocess.run(f"ip link set {self._router.get_iface_to_client()} master {router_vrf}", shell=True, check=True)
        subprocess.run(f"ip link set {self._client.get_iface()} up", shell=True, check=True)
        subprocess.run(f"ip link set {self._router.get_iface_to_client()} up", shell=True, check=True)

        # Pair 2: router <-> server
        subprocess.run(f"ip link add {self._router.get_iface_to_server()} type veth peer name {self._server.get_iface()}", shell=True, check=True)

        subprocess.run(f"ip link set {self._router.get_iface_to_server()} master {router_vrf}", shell=True, check=True)
        subprocess.run(f"ip link set {self._server.get_iface()} master {server_vrf}", shell=True, check=True)
        subprocess.run(f"ip link set {self._router.get_iface_to_server()} up", shell=True, check=True)
        subprocess.run(f"ip link set {self._server.get_iface()} up", shell=True, check=True)

        # Configure IP
        subprocess.run(f"ip addr add {self._client.get_ipv4()}/24 dev {self._client.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip -6 addr add {self._client.get_ipv6()}/64 dev {self._client.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip addr add {self._router.get_ipv4_to_client()}/24 dev {self._router.get_iface_to_client()}", shell=True, check=True)
        subprocess.run(f"ip -6 addr add {self._router.get_ipv6_to_client()}/64 dev {self._router.get_iface_to_client()}", shell=True, check=True)
        subprocess.run(f"ip addr add {self._router.get_ipv4_to_server()}/24 dev {self._router.get_iface_to_server()}", shell=True, check=True)
        subprocess.run(f"ip -6 addr add {self._router.get_ipv6_to_server()}/64 dev {self._router.get_iface_to_server()}", shell=True, check=True)
        subprocess.run(f"ip addr add {self._server.get_ipv4()}/24 dev {self._server.get_iface()}", shell=True, check=True)
        subprocess.run(f"ip -6 addr add {self._server.get_ipv6()}/64 dev {self._server.get_iface()}", shell=True, check=True)

        # Enable IP forwarding on router
        subprocess.run(f"ip vrf exec {router_vrf} sysctl -w net.ipv4.ip_forward=1", shell=True, check=True)
        subprocess.run(f"ip vrf exec {router_vrf} sysctl -w net.ipv6.conf.all.forwarding=1", shell=True, check=True)

        # Add default routes
        client_table = self._logical_to_table[self.CLIENT_TAG]
        server_table = self._logical_to_table[self.SERVER_TAG]
        subprocess.run(f"ip route add default via {self._router.get_ipv4_to_client()} dev {self._client.get_iface()} table {client_table}", shell=True, check=True)
        subprocess.run(f"ip route add default via {self._router.get_ipv4_to_server()} dev {self._server.get_iface()} table {server_table}", shell=True, check=True)
        subprocess.run(f"ip -6 route add default via {self._router.get_ipv6_to_client()} dev {self._client.get_iface()} table {client_table}", shell=True, check=True)
        subprocess.run(f"ip -6 route add default via {self._router.get_ipv6_to_server()} dev {self._server.get_iface()} table {server_table}", shell=True, check=True)

        self.veths.extend([(self._client.get_iface(), self._router.get_iface_to_client()),
                           (self._router.get_iface_to_server(), self._server.get_iface())])

        self._health_check()

    def _health_check(self):
        self._client._wait_for_ipv6_dad()
        self._router._wait_for_ipv6_dad()
        self._server._wait_for_ipv6_dad()
        self._client.run(f"ping -c 1 -W 1 {self._router.get_ipv4_to_client()}")
        self._client.run(f"ping -c 1 -W 1 {self._router.get_ipv6_to_client()}")
        self._server.run(f"ping -c 1 -W 1 {self._router.get_ipv4_to_server()}")
        self._server.run(f"ping -c 1 -W 1 {self._router.get_ipv6_to_server()}")
        self._client.run(f"ping -c 1 -W 1 {self._server.get_ipv4()}")
        self._client.run(f"ping -c 1 -W 1 {self._server.get_ipv6()}")

    def cleanup(self) -> None:
        for veth, peer in self.veths:
            subprocess.run(f"ip link del {veth}", shell=True, stderr=subprocess.DEVNULL)
        for vrf in self._logical_to_physical.values():
            subprocess.run(f"ip link del {vrf}", shell=True, stderr=subprocess.DEVNULL)
        if self._selinux_mode == "Enforcing":
            subprocess.run("setenforce 1", shell=True, stderr=subprocess.DEVNULL)
        if self._firewalld_was_enabled:
            subprocess.run(["systemctl", "start", "firewalld"], check=True)
            while subprocess.run(["firewall-cmd", "--state"],
                                  capture_output=True, text=True).stdout.strip() != "running":
                time.sleep(1)
