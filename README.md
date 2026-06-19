# Net-Rule Test Framework

[![Core CI](https://github.com/lishuang1986/net-rule-test-framework/actions/workflows/CI-core.yaml/badge.svg)](https://github.com/lishuang1986/net-rule-test-framework/actions/workflows/CI-core.yaml)
[![Netns CI](https://github.com/lishuang1986/net-rule-test-framework/actions/workflows/CI-netns.yaml/badge.svg)](https://github.com/lishuang1986/net-rule-test-framework/actions/workflows/CI-netns.yaml)
[![TC CI](https://github.com/lishuang1986/net-rule-test-framework/actions/workflows/CI-TC.yaml/badge.svg)](https://github.com/lishuang1986/net-rule-test-framework/actions/workflows/CI-TC.yaml)
[![FW CI](https://github.com/lishuang1986/net-rule-test-framework/actions/workflows/CI-FW.yaml/badge.svg)](https://github.com/lishuang1986/net-rule-test-framework/actions/workflows/CI-FW.yaml)

**Write once. Run across netns, VRF, and VMs.**

## Overview

Automation testing framework for Linux network **rules** – iptables, TC, and beyond.

The framework decouples **topology** (how nodes are connected) from **infrastructure** (how nodes are executed). A test defines traffic patterns against a topology, and the same test can run across different infrastructure backends without modification. The provided examples illustrate usage with **Firewall** and **TC** rules, and the same structure applies to other rule‑based subsystems (e.g., OVS flows, OVN ACLs).

Without this abstraction, testing a single TC rule across netns, VRF, and VMs would require three separate test scripts with duplicated logic.

```
┌─────────────────────────────────────┐
│              Test Cases             │
│     (pytest, topology-agnostic)     │
├─────────────────────────────────────┤
│           Topology Layer            │
│   Client-Server | Router | ...      │
├─────────────────────────────────────┤
│        Infrastructure Layer         │
│        Netns | VRF | Libvirt        │
└─────────────────────────────────────┘
```

## Test Suites

The project currently includes the following test suites:

- **TC** — Traffic Control rule tests (`tests/tc/`)<br>
  Example: u32 match validation, demonstrating cross-backend rule testing
- **Firewall** — iptables and nftables rule tests (`tests/firewall/`)<br>
  Examples: drop, conntrack, cgroupv2 meta matching — verifying the framework's rule-type extensibility
- **RoCEv2** — RDMA/RoCEv2 experiments and tests (`tests/rocev2/`) — **primary focus**<br>
  Protocol behavior, performance methodology, and deep inspection — across transports, completion modes, and benchmarks.<br>
  Reuses the Client-Server topology on libvirt VMs with SoftRoCE (RXE). Netns/VRF backends do not support RDMA. See [README](tests/rocev2/README.md) for details.

## Topology

### Client-Server

Two directly connected nodes on the same subnet:

```
┌──────────┐                    ┌──────────┐
│  client  │────────────────────│  server  │
│ 10.0.0.2 │                    │ 10.0.0.1 │
└──────────┘                    └──────────┘
```

All traffic flows directly between the pair.

### Router

Three nodes forming two isolated subnets connected through a router:

```
┌──────────┐  10.0.1.0/24   ┌──────────┐  10.0.2.0/24   ┌──────────┐
│  client  │────────────────│  router  │────────────────│  server  │
│ 10.0.1.2 │                │ 10.0.1.1 │                │ 10.0.2.2 │
└──────────┘                │ 10.0.2.1 │                └──────────┘
                            └──────────┘
```

Traffic from client to server must be routed through the router node.

### Host-Router

Derived from **Router** topology. The router role is played by the host machine itself:

```
┌──────────┐              ┌───────────────┐              ┌──────────┐
│  client  │──────────────│  host/router  │──────────────│  server  │
│   veth   │              │  (localhost)  │              │   veth   │
└──────────┘              └───────────────┘              └──────────┘
```

The host's network stack performs routing/forwarding, allowing tests to validate local network rules (iptables, TC, etc.) in a controlled environment.

## Infrastructure

Supported backends:
- Netns (network namespaces)
- VRF (Virtual Routing and Forwarding) — basic support
- Libvirt VMs (Fedora/RHEL/CentOS based) — used for RoCEv2/RDMA tests

### Base Topologies

| Topology / Infra | netns | vrf         | libvirt |
|------------------|-------|-------------|---------|
| Client-Server    | ✅    | ✅ (POC)    | ✅      |
| Router           | ✅    | ✅ (POC)    | ❌      |

### Derived Topologies (from base topologies above)

| Topology / Infra | netns | vrf | libvirt | Based on       |
|------------------|-------|-----|---------|----------------|
| Host-Router      | ✅    | ❌  | ❌      | Router         |

## Prerequisites

### System Packages

```bash
# Fedora / RHEL / CentOS
sudo dnf install -y python3-pip libcgroup-tools iproute-tc iptables nftables \
    tcpdump wireshark \
    libibverbs-utils librdmacm-utils infiniband-diags

# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y python3-pip cgroup-tools iproute2 iptables nftables iputils-ping \
    tcpdump tshark \
    libibverbs-utils librdmacm-utils infiniband-diags
```

Or run the setup script which handles both distributions:

```bash
./scripts/setup.sh
```

> **RoCEv2 / RDMA tests** require Libvirt VMs. The framework automatically installs RDMA packages (`libibverbs-utils`, `librdmacm-utils`, `perftest`, etc.) inside the VMs via `virt-customize`. The host packages listed above are for running diagnostics on the host side.

### Python

It is recommended to use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Quick Start

```bash
# Run all commands from the project root

# Run tests with netns (default)
pytest --infra=netns

# Run tests with VRF (POC)
pytest --infra=vrf

# Run tests with Libvirt VMs (requires Fedora image prepared)
pytest --infra=libvirt

# Run all tests with verbose output and generate an HTML report
pytest tests -vv --html=report.html

# Run only firewall tests
pytest tests/firewall/

# Run only TC u32 match test
pytest tests/tc/test_filter_u32.py -vv -s

# Run RoCEv2 tests with libvirt infra
pytest tests/rocev2/test_rocev2.py --infra=libvirt -vv -s
# Note: netns infra currently does not support RoCEv2 tests
```

### Libvirt VM Environment Setup

Currently supports **Fedora/RHEL/CentOS** based VMs.

**Required pre-step (user action):**
1. Install system packages:
   ```bash
   sudo dnf install -y qemu-kvm libvirt virt-install libguestfs guestfs-tools wget sshpass
   sudo systemctl enable --now libvirtd
   ```

2. Download a Fedora Cloud image (example uses Fedora 44) and save as `fedora.qcow2`:
   ```bash
   cd /var/lib/libvirt/images
   # Example: Fedora 44 Cloud image
   sudo wget https://download.fedoraproject.org/pub/fedora/linux/releases/44/Cloud/x86_64/images/Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2
   sudo mv Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2 fedora.qcow2
   # You can use other Fedora versions or compatible images
   ```

That's it! The framework will automatically:
- Customize the image (set root password, enable SSH, install RDMA packages if needed)
- Create VM disks and start VMs
- Configure the environment for testing

**Note:** The image customization (`virt-customize`) runs only **once**. A marker file `.customized` will be created to skip future customizations.

## Extensibility

Thanks to the layered design (Topology / Infrastructure separation), you can easily add new execution backends or rule types without changing existing test cases.

### Adding a new backend (e.g., containers, VMs, physical machines)
1. Create a new infra class inheriting `BaseInfra`.
2. Implement `setup()` to create the environment (e.g., start containers, allocate IPs).
3. Implement `cleanup()` to tear down resources.
4. Implement node‑specific `run()` and `get()` methods (e.g., via `docker exec`, `ssh`).

See `framework/infra/netns/` for an example netns implementation.

### Adding a new rule type (e.g., XDP, eBPF, OVS flows)
- Define a new topology class (if needed) or extend node behaviour.
- The existing fixtures and environment management remain fully reusable.

### The class hierarchy

```
                      Node (ABC)
                     run() / get()
          ┌───────────┼────────┼────────────┐
          │           │        │            │
          ▼           ▼        ▼            ▼
        NetnsNode  VrfNode  HostNode  LibvirtVMNode


ClientServerTopo (ABC)                BaseInfra (ABC)
  Client (Node)     Server (Node)    setup() / cleanup()
         │                │                  │
         └────────────────┼──────────────────┘
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
       NetnsClient   VrfClient    LibvirtClient
       ServerInfra   ServerInfra  ServerInfra


RouterTopo (ABC)                                  (same BaseInfra)
  Client (Node)   Router (Node)     Server (Node)
       │               │                  │                │
       └───────────────┼──────────────────┼────────────────┘
                       │                  │
              ┌────────┘                  └────────┐
              ▼                                    ▼
      NetnsRouterInfra                    NetnsHostRouterInfra
      VrfRouterInfra
```

## Author

Designed and implemented by **Li Shuang**.

## License

MIT License. See [LICENSE](LICENSE) for details.
