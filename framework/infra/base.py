# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
from abc import ABC, abstractmethod
import subprocess
import time
from typing import Dict


class BaseInfra(ABC):
    
    verbose = False
    
    @classmethod
    def set_verbose(cls, enabled: bool):
        cls.verbose = enabled
    
    @abstractmethod
    def setup(self) -> Dict[str, str]:
        pass
    
    @abstractmethod
    def cleanup(self):
        pass

    def _execute(self, cmd: str, tag: str = ""):
        if self.__class__.verbose:
            if tag:
                print(f"[{tag}] $ {cmd}")
            else:
                print(f"$ {cmd}")
        
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if self.__class__.verbose:
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
            if check and result.returncode != 0:
                raise AssertionError(
                    f"Command failed with exit code {result.returncode}\n"
                    f"Command: {cmd}\n{result.stderr}"
                )
        return result


class NetnsNode:
    """Base class for netns nodes, provides common run() implementation"""
    def __init__(self, executor, name: str, tag: str):
        self._executor = executor
        self._name = name
        self._tag = tag

    def run(self, cmd: str, check: bool = True, expect: str = "passed"):
        physical_ns = self._executor._logical_to_physical[self._name]
        full_cmd = f"ip netns exec {physical_ns} {cmd}"
        result = self._executor._execute(full_cmd, tag=self._tag)
        return self._executor._check_result(result, cmd, check, expect)

    def _wait_for_ipv6_dad(self, timeout: float = 3.0) -> bool:
        """Wait for IPv6 DAD to complete inside this node's netns."""
        physical_ns = self._executor._logical_to_physical[self._name]
        deadline = time.time() + timeout
        while time.time() < deadline:
            ret = subprocess.run(
                f"ip netns exec {physical_ns} ip -6 addr show tentative 2>/dev/null | grep -c tentative",
                shell=True, capture_output=True, text=True)
            count = ret.stdout.strip()
            if count == "" or int(count) == 0:
                return True
            time.sleep(0.2)
        return False


class VrfNode:
    """Base class for VRF nodes, executes commands via ip vrf exec"""
    def __init__(self, executor, name: str, tag: str):
        self._executor = executor
        self._name = name
        self._tag = tag

    def run(self, cmd: str, check: bool = True, expect: str = "passed"):
        # Get VRF name (assuming executor has _logical_to_physical mapping)
        vrf_name = self._executor._logical_to_physical[self._name]
        full_cmd = f"ip vrf exec {vrf_name} {cmd}"
        result = self._executor._execute(full_cmd, tag=self._tag)
        return self._executor._check_result(result, cmd, check, expect)

    def _wait_for_ipv6_dad(self, timeout: float = 3.0) -> bool:
        """Wait for IPv6 DAD to complete (VRF interfaces are on host)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            ret = subprocess.run(
                "ip -6 addr show tentative 2>/dev/null | grep -c tentative",
                shell=True, capture_output=True, text=True)
            count = ret.stdout.strip()
            if count == "" or int(count) == 0:
                return True
            time.sleep(0.2)
        return False


class HostNode:
    """Base class for local host nodes, executes commands directly (no netns)"""
    def __init__(self, executor, name: str, tag: str):
        self._executor = executor
        self._name = name
        self._tag = tag

    def run(self, cmd: str, check: bool = True, expect: str = "passed"):
        # Execute directly, no prefix added
        result = self._executor._execute(cmd, tag=self._tag)
        return self._executor._check_result(result, cmd, check, expect)

    def _wait_for_ipv6_dad(self, timeout: float = 3.0) -> bool:
        """Wait for IPv6 DAD to complete on the host."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            ret = subprocess.run(
                "ip -6 addr show tentative 2>/dev/null | grep -c tentative",
                shell=True, capture_output=True, text=True)
            count = ret.stdout.strip()
            if count == "" or int(count) == 0:
                return True
            time.sleep(0.2)
        return False
