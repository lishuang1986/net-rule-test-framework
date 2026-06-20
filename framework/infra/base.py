# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
from abc import ABC, abstractmethod
import subprocess
from ..topo.node import Node


class BaseInfra(ABC):

    @abstractmethod
    def setup(self) -> None:
        pass

    @abstractmethod
    def cleanup(self) -> None:
        pass


class NetnsNode(Node):
    """Base class for netns nodes, provides common run() implementation"""
    def __init__(self, infra, name: str, tag: str):
        self._infra = infra
        self._name = name
        self._tag = tag

    def run(
        self, cmd: str, check: bool = True, expect: str = "passed", silent: bool = False
    ) -> subprocess.CompletedProcess[str]:
        physical_ns = self._infra._logical_to_physical[self._name]
        full_cmd = f"ip netns exec {physical_ns} {cmd}"
        result = self._execute(full_cmd, tag=self._tag, silent=silent)
        return self._check_result(result, cmd, check, expect)

    def popen(self, cmd: str) -> subprocess.Popen[str]:
        physical_ns = self._infra._logical_to_physical[self._name]
        full_cmd = f"ip netns exec {physical_ns} {cmd}"
        if self.__class__.verbose:
            print(f"[{self._tag}] $ {full_cmd} &")
        return subprocess.Popen(
            full_cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

    def get(
        self, src: str, dst: str
    ) -> subprocess.CompletedProcess[str]:
        """Copy a file from the host to this netns node via cp.

        NetnsNode shares the host filesystem, so cp works directly.

        Args:
            src: Source path on the host
            dst: Destination path on this node
        """
        cmd = f"cp {src} {dst}"
        result = self._execute(cmd, tag=self._tag)
        return self._check_result(result, cmd)

class VrfNode(Node):
    """Base class for VRF nodes, executes commands via ip vrf exec"""
    def __init__(self, infra, name: str, tag: str):
        self._infra = infra
        self._name = name
        self._tag = tag

    def run(
        self, cmd: str, check: bool = True, expect: str = "passed", silent: bool = False
    ) -> subprocess.CompletedProcess[str]:
        # Get VRF name (assuming infra has _logical_to_physical mapping)
        vrf_name = self._infra._logical_to_physical[self._name]
        full_cmd = f"ip vrf exec {vrf_name} {cmd}"
        result = self._execute(full_cmd, tag=self._tag, silent=silent)
        return self._check_result(result, cmd, check, expect)

    def popen(self, cmd: str) -> subprocess.Popen[str]:
        vrf_name = self._infra._logical_to_physical[self._name]
        full_cmd = f"ip vrf exec {vrf_name} {cmd}"
        if self.__class__.verbose:
            print(f"[{self._tag}] $ {full_cmd} &")
        return subprocess.Popen(
            full_cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

    def get(
        self, src: str, dst: str
    ) -> subprocess.CompletedProcess[str]:
        """Copy a file from the host to this VRF node via cp.

        VrfNode shares the host filesystem, so cp works directly.

        Args:
            src: Source path on the host
            dst: Destination path on this node
        """
        cmd = f"cp {src} {dst}"
        result = self._execute(cmd, tag=self._tag)
        return self._check_result(result, cmd)

class HostNode(Node):
    """Base class for local host nodes, executes commands directly (no netns)"""
    def __init__(self, infra, name: str, tag: str):
        self._infra = infra
        self._name = name
        self._tag = tag

    def run(
        self, cmd: str, check: bool = True, expect: str = "passed", silent: bool = False
    ) -> subprocess.CompletedProcess[str]:
        result = self._execute(cmd, tag=self._tag, silent=silent)
        return self._check_result(result, cmd, check, expect)

    def popen(self, cmd: str) -> subprocess.Popen[str]:
        if self.__class__.verbose:
            print(f"[{self._tag}] $ {cmd} &")
        return subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

    def get(
        self, src: str, dst: str
    ) -> subprocess.CompletedProcess[str]:
        """Copy a file on the host (cp wrapper).

        Args:
            src: Source path
            dst: Destination path
        """
        cmd = f"cp {src} {dst}"
        result = self._execute(cmd, tag=self._tag)
        return self._check_result(result, cmd)

class LibvirtVMNode(Node):
    """Node that executes commands via SSH on a libvirt VM.

    Currently supports Fedora/RHEL/CentOS based VMs with:
    - Root password set to 'rdma'
    - SSH password authentication enabled
    - sshpass installed on host for SSH automation
    """

    def __init__(self, infra, name: str, tag: str):
        self._infra = infra
        self._name = name
        self._tag = tag

    def run(
        self, cmd: str, check: bool = True, expect: str = "passed", silent: bool = False
    ) -> subprocess.CompletedProcess[str]:
        ip = self._infra._logical_to_ip[self._name]
        ssh_user = self._infra.ssh_user
        ssh_password = self._infra.ssh_password
        full_cmd = f"sshpass -p '{ssh_password}' ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {ssh_user}@{ip} '{cmd}'"
        result = self._execute(full_cmd, tag=self._tag, silent=silent)
        return self._check_result(result, cmd, check, expect)

    def popen(self, cmd: str) -> subprocess.Popen[str]:
        ip = self._infra._logical_to_ip[self._name]
        ssh_user = self._infra.ssh_user
        ssh_password = self._infra.ssh_password
        full_cmd = f"sshpass -p '{ssh_password}' ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {ssh_user}@{ip} '{cmd}'"
        if self.__class__.verbose:
            print(f"[{self._tag}] $ {full_cmd} &")
        return subprocess.Popen(
            full_cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

    def get(
        self, src: str, dst: str
    ) -> subprocess.CompletedProcess[str]:
        """Copy a file from the host to this VM via scp.

        Args:
            src: Source path on the host
            dst: Destination path on this VM
        """
        ip = self._infra._logical_to_ip[self._name]
        ssh_user = self._infra.ssh_user
        ssh_password = self._infra.ssh_password
        cmd = (
            f"sshpass -p '{ssh_password}' "
            f"scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            f"{src} {ssh_user}@{ip}:{dst}"
        )
        result = self._execute(cmd, tag=self._tag)
        return self._check_result(result, cmd)

