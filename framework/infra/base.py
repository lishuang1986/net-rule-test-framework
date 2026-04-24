# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
from abc import ABC, abstractmethod
import subprocess
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
