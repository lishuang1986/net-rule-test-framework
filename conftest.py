# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
from framework.infra.netns.client_server import NetnsClientServerInfra
from framework.infra.netns.host_router import NetnsHostRouterInfra
from framework.infra.netns.router import NetnsRouterInfra
from framework.infra.vrf.client_server import VrfClientServerInfra
from framework.infra.vrf.router import VrfRouterInfra
from framework.infra.libvirt.client_server import LibvirtClientServerInfra
from framework.infra.base import BaseInfra


def pytest_addoption(parser):
    parser.addoption("--infra", default="netns", choices=["netns", "vrf", "libvirt"])


def pytest_configure(config):
    verbosity = config.option.verbose
    if verbosity >= 2:
        BaseInfra.set_verbose(True)
    else:
        BaseInfra.set_verbose(False)


@pytest.fixture
def client_server_env(request):
    infra_type = request.config.getoption("--infra")
    if infra_type == "netns":
        infra = NetnsClientServerInfra()
    elif infra_type == "vrf":
        infra = VrfClientServerInfra()
    elif infra_type == "libvirt":
        infra = LibvirtClientServerInfra()
    else:
        raise ValueError(f"Unknown infra: {infra_type}")
    try:
        infra.setup()
        yield infra
    finally:
        infra.cleanup()


@pytest.fixture
def host_router_env():
    infra = NetnsHostRouterInfra()
    try:
        infra.setup()
        yield infra
    finally:
        infra.cleanup()


@pytest.fixture
def router_env(request):
    infra_type = request.config.getoption("--infra")
    if infra_type == "netns":
        infra = NetnsRouterInfra()
    elif infra_type == "vrf":
        infra = VrfRouterInfra()
    else:
        raise ValueError(f"Unknown infra: {infra_type}")
    try:
        infra.setup()
        yield infra
    finally:
        infra.cleanup()


@pytest.fixture
def rocev2_env(request):
    """RoCEv2 test environment with RDMA setup.

    Uses --infra option to select infrastructure (libvirt, netns, vrf).
    Automatically calls setup_rdma() after infrastructure setup.
    """
    infra_type = request.config.getoption("--infra")

    if infra_type == "libvirt":
        infra = LibvirtClientServerInfra()
    elif infra_type == "netns":
        infra = NetnsClientServerInfra()
    elif infra_type == "vrf":
        infra = VrfClientServerInfra()
    else:
        raise ValueError(f"Unknown infra for rocev2: {infra_type}")

    try:
        infra.setup()
        infra.setup_rdma()
        yield infra
    finally:
        infra.cleanup()
