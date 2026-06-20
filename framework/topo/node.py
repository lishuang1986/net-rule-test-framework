# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
from abc import ABC, abstractmethod
import subprocess
import time


class Node(ABC):
    """Abstract base class for all node types.

    Defines the common interface that all concrete node implementations
    (NetnsNode, VrfNode, HostNode, LibvirtVMNode) must provide.
    """

    verbose = False

    @classmethod
    def set_verbose(cls, enabled: bool) -> None:
        cls.verbose = enabled

    @abstractmethod
    def run(self, cmd: str, check: bool = True, expect: str = "passed",
            silent: bool = False
    ) -> subprocess.CompletedProcess[str]:
        """Execute a command on this node and wait for completion"""
        pass

    @abstractmethod
    def popen(self, cmd: str) -> subprocess.Popen[str]:
        """Start a command on this node in background, return Popen handle"""
        pass

    @abstractmethod
    def get(self, src: str, dst: str) -> subprocess.CompletedProcess[str]:
        """Copy a file from the host to this node"""
        pass

    def _execute(self, cmd: str, tag: str = "", silent: bool = False):
        if self.__class__.verbose:
            if tag:
                print(f"[{tag}] $ {cmd}")
            else:
                print(f"$ {cmd}")

        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, errors='replace')

        if self.__class__.verbose and not silent:
            if result.stdout:
                print(f"[STDOUT]\n{result.stdout.rstrip()}")
            if result.stderr:
                print(f"[STDERR] {result.stderr.rstrip()}")
            if result.returncode != 0:
                print(f"[RETURN] {result.returncode}")
            print("-" * 40)

        return result

    def _check_result(self, result, cmd: str, check: bool = True, expect: str = "passed"):
        """Unified result check logic"""
        if not check:
            return result

        if expect == "failed":
            if result.returncode == 0:
                raise AssertionError(f"Expected failure, but command succeeded.\nCommand: {cmd}")
        elif expect == "passed":
            if result.returncode != 0:
                raise AssertionError(
                    f"Command failed with exit code {result.returncode}\n"
                    f"Command: {cmd}\n{result.stderr}"
                )
        else:
            pass
        return result

    def _wait_for_ipv6_dad(self, timeout: float = 3.0) -> bool:
        """Wait for IPv6 DAD to complete on this node."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            ret = self.run(
                "ip -6 addr show tentative 2>/dev/null | grep -c tentative",
                check=False
            )
            count = ret.stdout.strip()
            if count == "" or int(count) == 0:
                return True
            time.sleep(0.2)
        return False


class Client(Node):
    """Client node interface, shared by all topologies"""

    @staticmethod
    def get_iface_rdma() -> str:
        """Return the RDMA RXE interface name"""
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
    """Server node interface, shared by all topologies"""

    @staticmethod
    def get_iface_rdma() -> str:
        """Return the RDMA RXE interface name"""
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


class Router(ABC):
    """Router node interface, shared by router topologies"""

    @abstractmethod
    def get_ipv4_to_client(self) -> str:
        pass

    @abstractmethod
    def get_ipv4_to_server(self) -> str:
        pass

    @abstractmethod
    def get_ipv6_to_client(self) -> str:
        pass

    @abstractmethod
    def get_ipv6_to_server(self) -> str:
        pass

    @abstractmethod
    def get_iface_to_client(self) -> str:
        pass

    @abstractmethod
    def get_iface_to_server(self) -> str:
        pass
