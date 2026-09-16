# RoCEv2 / RDMA Experiments

This directory contains structured, reproducible experiments for RDMA (Remote Direct Memory Access) over Converged Ethernet (RoCEv2). Each experiment is implemented as a pytest test case, sharing the project's reusable environment fixtures to automate VM lifecycle and RDMA device configuration.

> These experiments are performed in a **SoftRoCE (RXE)** software-emulated environment, not on physical RDMA NICs. The focus is on understanding RDMA concepts — transport types, completion mechanisms, memory registration — and building a systematic methodology for performance analysis. All test code is written against the framework's topology/infrastructure abstraction, so switching to real RDMA hardware requires only a new infra backend — the test cases themselves remain unchanged.

## Directory Structure

| File | Purpose |
|------|---------|
| `test_smoke.py` | Device discovery, basic RDMA connectivity, trace-cmd kernel tracing |
| `test_pingpong.py` | `ibv_pingpong` — RC/UC/UD transport comparison, message size benchmarks |
| `test_ib_write_bw.py` | `ib_write_bw` bandwidth — CM variants, QP count scaling, netem loss |
| `test_ib_send_bw.py` | `ib_send_bw` bandwidth — CM variants, server-ingress loss and RC retransmission |
| `test_ib_write_lat.py` | `ib_write_lat` latency — CM variants |
| `test_bench_bw_qdisc.py` | Cross-operation bandwidth comparison under netem loss |
| `test_rdma_send.py` | Custom RDMA Send with poll/event/hybrid completion modes |
| `test_rping.py` | `rping` connectivity (IPv4/IPv6) with tcpdump packet capture |
| `utils.py` | Output parsers for pingpong, perftest, and iperf3 |
| `rdma_send_server.c` / `rdma_send_client.c` | Custom librdmacm + libibverbs RDMA Send implementation |

## Experiments

### 1. Device Discovery and Diagnostics

**Source:** `test_smoke.py`

Verify that SoftRoCE devices are properly loaded and accessible via standard RDMA diagnostic tools:

- `ibv_devinfo` / `ibv_devices` — device capability enumeration
- `ibstat` / `ibstatus` — device state and port status
- `rdma_server` / `rdma_client` — basic connection establishment

### 2. RDMA Transport Comparison (RC / UC / UD)

**Source:** `test_pingpong.py` — `test_ibv_pingpong_ipv4` (parametrized: `rc` / `uc` / `ud`)

Compare the three InfiniBand transport services using `ibv_pingpong`:

| Transport | Type | Description |
|-----------|------|-------------|
| **RC** (Reliable Connection) | Connection-oriented | Reliable, in-order delivery, retransmission |
| **UC** (Unreliable Connection) | Connection-oriented | No retransmission, no ACK |
| **UD** (Unreliable Datagram) | Connectionless | Datagram delivery, limited MTU |

Each test captures both the RoCEv2 data path (UDP 4791) and the RDMA CM channel (TCP 18515) with tcpdump for protocol-level inspection. An IPv6 variant is skipped because `ibv_rc_pingpong` IPv6 support is unreliable.

### 3. Message Size Benchmarking

**Source:** `test_pingpong.py` — `test_ibv_rc_pingpong_bench_by_size`

Measure latency and throughput across message sizes (1B, 1K, 4K, 8K, 16K) with terminal-rendered charts via the `plotext` library. Both client and server metrics are captured for symmetry analysis.

### 4. Kernel Tracing with trace-cmd

**Source:** `test_smoke.py` — `test_librdmacm_utils_trace_event`, `test_librdmacm_utils_trace_func`

- **trace-cmd event recording** (`-e rdma_cma:* -e rdma_core:*`) — captures RDMA CM state transitions and core verb events
- **trace-cmd function tracing** (`-p function_graph -l 'rxe_*' -l 'ib_*' -l 'rdma_*' -l 'cm_*'`) — captures kernel function calls in the SoftRoCE driver, enabling deep inspection of the driver's internal code paths

### 5. Bandwidth Benchmarks (ib_write_bw / ib_send_bw)

**Source:** `test_ib_write_bw.py`, `test_ib_send_bw.py`

Using the standard `perftest` suite to measure RDMA bandwidth. Both files cover the same connection-management / address-family matrix, each adding its own stress scenarios:

- **CM / address-family matrix** — IPv4/IPv6 × RDMA CM (`-R`) / TCP CM (QP info over TCP 18515)
- `test_ib_write_bw_bench_by_QP` — Queue Pair scaling (1 / 2 / 4 / 8 / 16 / 32 QPs), measuring how multi-stream parallelism affects aggregate bandwidth
- `test_ib_write_bw_bench_netem_loss` — bandwidth under client-egress netem loss (0.01% – 0.5%)
- `test_ib_send_bw_*_netem_loss` — 2% server-ingress loss applied only to RoCEv2 data packets (an ingress flower filter redirects UDP 4791 to an `ifb0` netem qdisc), leaving TCP control traffic untouched; the client-side capture then shows RC retransmissions as duplicate PSNs
- `test_ib_{write,send}_bw_all` — `-a` (all tests in a single connection)

### 6. Latency Benchmarks (ib_write_lat)

**Source:** `test_ib_write_lat.py`

Measure RDMA write latency with `ib_write_lat` across the same CM / address-family matrix (IPv4/IPv6 × RDMA CM / TCP CM), plus `-a` to run all sizes in a single connection. Packet capture covers RoCEv2 (UDP 4791) and the TCP CM channel (18515).

### 7. Cross-Operation Bandwidth Comparison (netem loss)

**Source:** `test_bench_bw_qdisc.py` — `test_bench_bw_qdisc_netem_loss`

Run four operations — `ib_write_bw`, `ib_read_bw`, `ib_send_bw`, and `iperf3` TCP — under 0%, 0.1%, and 0.5% netem loss applied to both endpoints, then print a comparison table of average bandwidth and degradation relative to the loss-free baseline. This contrasts RDMA's loss-recovery behavior with TCP's congestion response on the same link.

### 8. RDMA Send Completion Modes

**Source:** `test_rdma_send.py`

Custom C programs (`rdma_send_server.c` / `rdma_send_client.c`) using `librdmacm` for connection management and `libibverbs` for data transfer, implementing three completion strategies:

| Mode | WC Retrieval | Description |
|------|-------------|-------------|
| **Polling** | `ibv_poll_cq()` | Busy-wait loop, lowest latency, 100% CPU |
| **Event-driven** | `ibv_get_cq_event()` | Blocking wait, CPU-efficient |
| **Hybrid** | Event + poll | Event trigger followed by poll drain |

Each mode is exercised end-to-end with RoCEv2 (UDP 4791) and RDMA CM (TCP 7474) packet capture.

### 9. Packet Capture Analysis

**Source:** `test_rping.py`

Uses `rping` for RDMA ping-pong over both IPv4 and IPv6 with:
- tcpdump/tshark packet capture (filtered to UDP 4791 for RoCEv2 traffic)
- Protocol-level inspection of RDMA CM connection establishment and data exchange

## Limitations

- **Infrastructure dependency**: RoCEv2 tests currently require `--infra=libvirt`; only libvirt's `ClientServerInfra` configures SoftRoCE (RXE) on VMs. SoftRoCE support on the netns/VRF backends is still incomplete — experiments on both Fedora 44 and Ubuntu 24.04 VMs ran into issues, so those backends are not yet usable for RDMA tests.
- **CI feasibility**: As a result, GitHub CI does not yet cover the RoCEv2 / RDMA experiments in this directory. Running them requires an RDMA-capable environment (physical hardware or nested virtualization).

## Running

```bash
# From the project root
pytest tests/rocev2/ --infra=libvirt -vv -s
```
