# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
from abc import ABC, abstractmethod


class Node(ABC):
    """Abstract base class for all node types.

    Defines the common interface that all concrete node implementations
    (NetnsNode, VrfNode, HostNode, LibvirtVMNode) must provide.
    """

    @abstractmethod
    def run(self, cmd: str, check: bool = True, expect: str = "passed",
            background: bool = False, silent: bool = False):
        """Execute a command on this node"""
        pass

    @abstractmethod
    def get(self, src: str, dst: str, check: bool = True, silent: bool = False):
        """Copy a file from the host to this node"""
        pass
