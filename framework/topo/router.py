# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
from abc import ABC, abstractmethod


class RouterTopo(ABC):
    """Router topology base class - defines interfaces for nodes to implement"""
    
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

    class Router(ABC):
        @abstractmethod
        def get_ip_to_client(self) -> str:
            pass

        @abstractmethod
        def get_ip_to_server(self) -> str:
            pass

        @abstractmethod
        def get_iface_to_client(self) -> str:
            pass

        @abstractmethod
        def get_iface_to_server(self) -> str:
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
