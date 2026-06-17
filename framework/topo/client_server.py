# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
from abc import ABC, abstractmethod
from .node import Node


class ClientServerTopo(ABC):
    """Client-Server topology base class - defines interfaces for nodes to implement"""

    def setup_rdma(self):
        """Setup RDMA (rdma_rxe) on client and server nodes"""
        for node in [self.Client, self.Server]:
            iface = node.get_iface()
            rdma_dev = node.get_iface_rdma()
            node.run("modprobe rdma_rxe")
            node.run(f"rdma link add {rdma_dev} type rxe netdev {iface} 2>/dev/null || true")
            node.run("rdma link show -d")
            node.run(f"cat /sys/class/infiniband/{rdma_dev}/ports/1/gids/2")

    class Client(Node):
        def get_iface_rdma(self) -> str:
            """Return the RDMA interface name"""
            return "rxe_client"

        @abstractmethod
        def get_ipv4(self) -> str:
            pass

        @abstractmethod
        def get_ipv6(self) -> str:
            pass

        @abstractmethod
        def get_iface(self) -> str:
            pass

    class Server(Node):
        def get_iface_rdma(self) -> str:
            """Return the RDMA interface name"""
            return "rxe_server"

        @abstractmethod
        def get_ipv4(self) -> str:
            pass

        @abstractmethod
        def get_ipv6(self) -> str:
            pass

        @abstractmethod
        def get_iface(self) -> str:
            pass
