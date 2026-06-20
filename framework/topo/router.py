# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
from abc import ABC, abstractmethod

from .node import Client, Router, Server


class RouterTopo(ABC):
    """Router topology base class"""

    @property
    @abstractmethod
    def Client(self) -> Client:
        ...

    @property
    @abstractmethod
    def Router(self) -> Router:
        ...

    @property
    @abstractmethod
    def Server(self) -> Server:
        ...
