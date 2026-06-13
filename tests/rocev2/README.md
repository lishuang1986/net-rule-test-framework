# RoCEv2 / RDMA Experiment Scripts

This directory contains automated verification and debugging scripts I wrote while learning RDMA (Remote Direct Memory Access) and the RoCEv2 protocol stack.
**This is not a "formal" test suite, but a set of reproducible experiment notes** used to record and verify RDMA device configuration, basic communication, and performance testing.

## Experiment Goals

- Quickly verify that RDMA hardware devices are properly loaded with the correct drivers
- Automate running commands like `ibv_devinfo` and `ibstat` to get familiar with device status information
- Measure point-to-point bandwidth and latency using the `perftest` toolset (`ib_write_bw`, `ib_read_bw`)
- Experiment with the low-level interfaces provided by `libibverbs` and `librdmacm` to understand fundamental concepts such as QP (Queue Pair) creation, send/receive operations, and memory registration

## Design Philosophy

Although these are learning-oriented scripts, I still reuse the project's **pytest + layered architecture** for the following benefits:

- Clean `setup` / `teardown` environment management (automatic VM creation, RDMA device configuration)
- Parameterized test cases for easy comparison of different configurations (e.g., MTU, GID type)
- Real-time logging to observe RDMA handshake details

The scripts in this directory obtain an RDMA-ready test environment via the `rocev2_env` fixture, which selects the underlying implementation based on the `--infra` parameter (currently primarily supports `libvirt`, using pre-built "golden images" and hardware passthrough).

## Current Progress

### Completed Experiments

- Device availability check (`ibv_devinfo`)
- Basic connectivity and bandwidth tests (`ib_write_bw` / `ib_read_bw`)
- Simple interactions using the low-level interfaces of `libibverbs` and `librdmacm`

### Next Steps

- **Packet loss and reordering simulation**: Integrate with this framework's TC (Traffic Control) module to inject packet loss, latency, or reordering into RDMA links, and observe RoCEv2's congestion control and retransmission behavior.
- **Multi-connection concurrent testing**: Use multiple QP pairs to transmit simultaneously, verifying the driver and hardware's concurrent processing capabilities.

## Limitations

- **CI environment constraints**: Since RDMA testing requires real physical hardware or a nested virtualization-capable runtime, the scripts in this directory cannot run on standard public CI platforms such as GitHub Actions.

- **Hardware emulation environment**: Due to the hardware limitations of my personal development environment, all experiments are currently conducted in a **Soft RoCE (RXE)** software emulation environment rather than on real RDMA NICs. Therefore, test results may differ from real hardware (e.g., Mellanox ConnectX series) in terms of performance, latency, and congestion control behavior. The primary value lies in understanding the concepts rather than performance comparison.
