# RoCEv2 / RDMA Experiments

This directory contains structured, reproducible experiments for RDMA (Remote Direct Memory Access) over Converged Ethernet (RoCEv2). Each experiment is implemented as a pytest test case, sharing the project's reusable environment fixtures to automate VM lifecycle and RDMA device configuration.

> These experiments are performed in a **SoftRoCE (RXE)** software-emulated environment, not on physical RDMA NICs. The focus is on understanding RDMA concepts — transport types, completion mechanisms, memory registration — and building a systematic methodology for performance analysis. All test code is written against the framework's topology/infrastructure abstraction, so switching to real RDMA hardware requires only a new infra backend — the test cases themselves remain unchanged.

## Directory Structure

| File | Purpose |
|------|---------|
| `test_rocev2.py` | Device discovery and basic RDMA connectivity |
| `test_pingpong.py` | `ibv_pingpong` — RC/UC/UD transport comparison, message size benchmarks, perf profiling |
| `test_ib_write_bw.py` | Bandwidth benchmarks — MTU effect, QP count scaling |
| `test_rdma_send.py` | Custom RDMA Send with poll/event/hybrid completion modes, latency, perf, trace-cmd |
| `test_rping.py` | `rping` connectivity test with tcpdump packet capture |
| `utils.py` | Output parsers for pingpong, perftest, perf stat, and perf report |
| `rdma_send_server.c` / `rdma_send_client.c` | Custom librdmacm + libibverbs RDMA Send implementation |

## Experiments

### 1. Device Discovery and Diagnostics

**Source:** `test_rocev2.py`

Verify that SoftRoCE devices are properly loaded and accessible via standard RDMA diagnostic tools:

- `ibv_devinfo` / `ibv_devices` — device capability enumeration
- `ibstat` / `ibstatus` — device state and port status
- `rdma_server` / `rdma_client` — basic connection establishment

### 2. RDMA Transport Comparison (RC / UC / UD)

**Source:** `test_pingpong.py` — `test_ibv_pingpong_ipv4`

Compare the three InfiniBand transport services using `ibv_pingpong`:

| Transport | Type | Description |
|-----------|------|-------------|
| **RC** (Reliable Connection) | Connection-oriented | Reliable, in-order delivery, retransmission |
| **UC** (Unreliable Connection) | Connection-oriented | No retransmission, no ACK |
| **UD** (Unreliable Datagram) | Connectionless | Datagram delivery, limited MTU |

Each test captures RoCEv2 traffic (UDP 4791) with tcpdump for protocol-level inspection.

### 3. Message Size Benchmarking

**Source:** `test_pingpong.py` — `test_ibv_rc_pingpong_bench_by_size`

Measure latency and throughput across message sizes (1B, 1K, 4K, 8K, 16K) with terminal-rendered charts via the `plotext` library. Both client and server metrics are captured for symmetry analysis.

### 4. Performance Profiling with perf

**Source:** `test_pingpong.py` — `test_ibv_rc_pingpong_perf_stat`, `test_ibv_rc_pingpong_perf_record`

Systematic CPU performance analysis of RDMA operations across message sizes:

- **perf stat** — hardware counters: cycles, instructions, cache references/misses, context switches
- **Derived metrics**: IPC (instructions per cycle), cache miss rate, CPU utilization
- **perf record/report** — hotspot function analysis identifying the most CPU-intensive kernel and user-space routines (e.g., `rxe_post_send`, `rxe_completer`)

### 5. Bandwidth Benchmarks (ib_write_bw)

**Source:** `test_ib_write_bw.py`

Using the standard `perftest` suite to measure RDMA write bandwidth:

- `test_ib_write_bw` — baseline bandwidth measurement (1MB message)
- `test_ib_write_bw_bench_by_mtu` — active MTU comparison (1K / 2K / 4K) with end-to-end MTU verification via ping with DF flag
- `test_ib_write_bw_bench_by_QP` — Queue Pair scaling (1 / 2 / 4 / 8 QPs), measuring how multi-stream parallelism affects aggregate bandwidth

### 6. RDMA Send Completion Modes

**Source:** `test_rdma_send.py`

Custom C programs (`rdma_send_server.c` / `rdma_send_client.c`) using `librdmacm` for connection management and `libibverbs` for data transfer, implementing three completion strategies:

| Mode | WC Retrieval | Description |
|------|-------------|-------------|
| **Polling** | `ibv_poll_cq()` | Busy-wait loop, lowest latency, 100% CPU |
| **Event-driven** | `ibv_get_cq_event()` | Blocking wait, CPU-efficient |
| **Hybrid** | Event + poll | Event trigger followed by poll drain |

Comparison dimensions:
- `test_rdma_send_latency_compare` — end-to-end latency measurement across modes
- `test_rdma_send_perf_stat` — CPU counter comparison (migrations, cycles, IPC)
- `test_rdma_send_perf_hotspot` — hotspot function analysis for each mode

### 7. Kernel Tracing with trace-cmd

**Source:** `test_rdma_send.py` — `*_trace_event` and `*_trace_func` variants

- **trace-cmd event recording** (`-e rdma_cma:* -e rdma_core:*`) — captures RDMA CM state transitions and core verb events
- **trace-cmd function tracing** (`-p function -l 'rxe_*'`) — captures kernel function calls in the SoftRoCE driver (`rxe_*`, `ib_*`, `rdma_*`, `cm_*`), enabling deep inspection of the driver's internal code paths

### 8. Packet Capture Analysis

**Source:** `test_rping.py`

Uses `rping` for RDMA ping-pong with:
- tcpdump/tshark packet capture (filtered to UDP 4791 for RoCEv2 traffic)
- Protocol-level inspection of RDMA CM connection establishment and data exchange

## Limitations

- **CI environment**: These tests require RDMA-capable environments (physical hardware or nested virtualization) and cannot run on standard CI platforms like GitHub Actions.
- **SoftRoCE emulation**: All experiments use SoftRoCE (RXE) software emulation. Performance characteristics (latency, bandwidth, congestion behavior) differ from hardware RDMA NICs (e.g., Mellanox ConnectX). The value lies in protocol understanding and measurement methodology, not absolute performance numbers.


## Running

```bash
# From the project root
pytest tests/rocev2/ --infra=libvirt -vv -s
```
