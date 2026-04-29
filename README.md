# Net-Rule Test Framework

**Network Rule Automation Testing Framework**

## Overview

Automation testing framework for Linux network **rules** – iptables, TC, and beyond.

The provided examples illustrate usage with **Netfilter/iptables** and **TC**. The same test structure applies to other rule‑based subsystems (e.g., OVS flows, OVN ACLs). The framework separates rule logic from environment setup, making it easy to add new rule types and backends.

Supported backends:
- Netns (network namespaces)
- VRF (Virtual Routing and Forwarding) – **experimental**

## Quick Start

```bash
# Run all commands from the project root

# Install dependencies
pip install -r requirements.txt

# Run tests with netns (default)
pytest --infra=netns

# Run tests with VRF (experimental)
pytest --infra=vrf

# Run all tests with verbose output and generate an HTML report
pytest tests -vv --html=report.html

# Run only netfilter tests
pytest tests/netfilter/ --infra=netns

# Run only TC u32 match test
pytest tests/tc/test_u32_match.py -vv
```

## Extensibility

Thanks to the layered design (Topology / Infrastructure separation), you can easily add new execution backends or rule types without changing existing test cases.

### Adding a new backend (e.g., containers, VMs, physical machines)
1. Create a new infra class inheriting `BaseInfra`.
2. Implement `setup()` to create the environment (e.g., start containers, allocate IPs).
3. Implement `cleanup()` to tear down resources.
4. Implement node‑specific `run()` methods (e.g., via `docker exec`, `ssh`).

### Adding a new rule type (e.g., XDP, eBPF, OVS flows)
- Define a new topology class (if needed) or extend node behaviour.
- The existing fixtures and environment management remain fully reusable.

See `framework/infra/netns/` for an example netns implementation.

## Author

This project is designed and implemented entirely by **Li Shuang** as a demonstration of testing framework architecture.

## License

MIT License. See [LICENSE](LICENSE) for details.
