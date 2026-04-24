# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
from abc import ABC, abstractmethod


class ClientServerTopo(ABC):
    """Client-Server topology base class - defines interfaces for nodes to implement"""
    
    class Client(ABC):
        @abstractmethod
        def get_ipv4(self) -> str:
            pass

        @abstractmethod
        def get_ipv6(self) -> str:
            pass

        @abstractmethod
        def get_iface(self) -> str:
            pass

    class Server(ABC):
        @abstractmethod
        def get_ipv4(self) -> str:
            pass

        @abstractmethod
        def get_ipv6(self) -> str:
            pass

        @abstractmethod
        def get_iface(self) -> str:
            pass
