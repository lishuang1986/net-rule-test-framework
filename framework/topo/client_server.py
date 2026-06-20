# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
from abc import ABC, abstractmethod

from .node import Client, Server


class ClientServerTopo(ABC):
    """Client-Server topology base class"""

    @property
    @abstractmethod
    def Client(self) -> Client:
        ...

    @property
    @abstractmethod
    def Server(self) -> Server:
        ...

    def setup_rdma(self):
        """Setup RDMA (rdma_rxe) on client and server nodes"""
        for node in [self.Client, self.Server]:
            iface = node.get_iface()
            rdma_dev = node.get_iface_rdma()
            node.run("modprobe rdma_rxe")
            node.run(
                f"rdma link add {rdma_dev} type rxe netdev {iface} 2>/dev/null || true"
            )
            node.run("rdma link show -d")
            node.run("show_gids")
