# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import os
import pytest
import time
from tests.rocev2.utils import parse_perf_stat_text, parse_perf_report, print_hotspot_report

pytestmark = [pytest.mark.rocev2]

_dir = os.path.dirname(__file__)
SRC_SERVER = os.path.join(_dir, "rdma_send_server.c")
SRC_CLIENT = os.path.join(_dir, "rdma_send_client.c")
DST_SERVER = "/tmp/rdma_send_server.c"
DST_CLIENT = "/tmp/rdma_send_client.c"
BIN_SERVER = "/tmp/rdma_send_server"
BIN_CLIENT = "/tmp/rdma_send_client"
TIMEOUT = 20


def _setup(rocev2_env):
    """Copy sources and compile on both nodes."""
    rocev2_env.Server.get(SRC_SERVER, DST_SERVER)
    rocev2_env.Client.get(SRC_CLIENT, DST_CLIENT)
    rocev2_env.Server.run(f"gcc -o {BIN_SERVER} {DST_SERVER} -lrdmacm -libverbs")
    rocev2_env.Client.run(f"gcc -o {BIN_CLIENT} {DST_CLIENT} -lrdmacm -libverbs")


def _run_test(rocev2_env, mode, server_assert):
    server_ip = rocev2_env.Server.get_ipv4()
    client_iface = rocev2_env.Client.get_iface()
    log_suffix = f"rdma_send_{mode}"
    server_log = f"/tmp/{log_suffix}_server.log"
    client_log = f"/tmp/{log_suffix}_client.log"
    pcap_file = f"/tmp/{log_suffix}.pcap"

    # Start tcpdump in background to capture RoCEv2 traffic (UDP port 4791)
    tcpdump_proc = rocev2_env.Client.run(
        f"tcpdump -U -i {client_iface} tcp port 7474 or udp port 4791 -w {pcap_file}",
        background=True
    )
    time.sleep(1)

    # Start server with specific mode in background
    server_proc = rocev2_env.Server.run(
        f"{BIN_SERVER} --mode {mode} > {server_log} 2>&1",
        background=True
    )
    time.sleep(2)

    try:
        # Run client with timeout to prevent hanging
        rocev2_env.Client.run(
            f"timeout {TIMEOUT} {BIN_CLIENT} --mode {mode} {server_ip} > {client_log} 2>&1",
            check=False
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

        # Stop tcpdump and wait for buffer flush
        tcpdump_proc.terminate()
        tcpdump_proc.wait()
        time.sleep(1)

        # Print and verify outputs
        server_result = rocev2_env.Server.run(f"cat {server_log}", check=False)
        client_result = rocev2_env.Client.run(f"cat {client_log}", check=False)

        # Display tcpdump capture — RoCEv2 (UDP 4791)
        rocev2_env.Client.run(f"tshark -r {pcap_file} -Y \"udp.port == 4791\"")
        # Display tcpdump capture — RDMA_CM over TCP (7474)
        rocev2_env.Client.run(f"tshark -r {pcap_file} -Y \"tcp.port == 7474\"")
        rocev2_env.Client.run(f"tcpdump -nn -r {pcap_file}")

        assert server_assert in server_result.stdout, \
            f"Server ({mode}) did not receive expected message"
        assert "Data sent successfully" in client_result.stdout, \
            f"Client ({mode}) did not report send success"


def _run_test_with_trace_event(rocev2_env, mode, server_assert):
    """Run RDMA send test with trace-cmd recording rdma_cma/rdma_core events on the server."""
    server_ip = rocev2_env.Server.get_ipv4()
    log_suffix = f"rdma_send_{mode}"
    server_log = f"/tmp/{log_suffix}_server.log"
    client_log = f"/tmp/{log_suffix}_client.log"
    trace_dat = f"/tmp/{log_suffix}_trace.dat"
    trace_report = f"/tmp/{log_suffix}_trace_report.log"

    # Start server under trace-cmd recording
    server_proc = rocev2_env.Server.run(
        f"trace-cmd record -o {trace_dat} -e rdma_cma:* -e rdma_core:* "
        f"{BIN_SERVER} --mode {mode} > {server_log}",
        background=True
    )
    time.sleep(2)

    try:
        # Run client with timeout to prevent hanging
        rocev2_env.Client.run(
            f"timeout {TIMEOUT} {BIN_CLIENT} --mode {mode} {server_ip} > {client_log}",
            check=False
        )
    finally:
        # Give trace-cmd time to flush trace data to disk
        time.sleep(1)
        server_proc.terminate()
        server_proc.wait()

        # Generate and display trace report
        rocev2_env.Server.run(
            f"trace-cmd report -i {trace_dat}"
        )

        # Verify outputs as usual
        server_result = rocev2_env.Server.run(f"cat {server_log}", check=False)
        client_result = rocev2_env.Client.run(f"cat {client_log}", check=False)

        assert server_assert in server_result.stdout, \
            f"Server ({mode}) did not receive expected message"
        assert "Data sent successfully" in client_result.stdout, \
            f"Client ({mode}) did not report send success"


def _run_test_with_trace_func(rocev2_env, mode, server_assert):
    """Run RDMA send test with trace-cmd recording kernel function calls on the server."""
    server_ip = rocev2_env.Server.get_ipv4()
    log_suffix = f"rdma_send_{mode}"
    server_log = f"/tmp/{log_suffix}_server.log"
    client_log = f"/tmp/{log_suffix}_client.log"
    trace_dat = f"/tmp/{log_suffix}_functrace.dat"
    trace_report = f"/tmp/{log_suffix}_functrace_report.log"

    # Start server under trace-cmd function_graph recording
    server_proc = rocev2_env.Server.run(
        f"trace-cmd record -p function -l 'rxe_*' -l 'ib_*' -l 'rdma_*' -l 'cm_*' -o {trace_dat} "
        f"{BIN_SERVER} --mode {mode} > {server_log}",
        background=True
    )
    time.sleep(2)

    try:
        # Run client with timeout to prevent hanging
        rocev2_env.Client.run(
            f"timeout {TIMEOUT} {BIN_CLIENT} --mode {mode} {server_ip} > {client_log}",
            check=False
        )
    finally:
        # Give trace-cmd time to flush trace data to disk
        time.sleep(3)
        server_proc.terminate()
        server_proc.wait()

        # Generate and display trace report
        rocev2_env.Server.run(
            f"trace-cmd report -i {trace_dat}"
        )

        # Verify outputs as usual
        server_result = rocev2_env.Server.run(f"cat {server_log}", check=False)
        client_result = rocev2_env.Client.run(f"cat {client_log}", check=False)

        assert server_assert in server_result.stdout, \
            f"Server ({mode}) did not receive expected message"
        assert "Data sent successfully" in client_result.stdout, \
            f"Client ({mode}) did not report send success"


def test_rdma_send_poll(rocev2_env):
    """Test RDMA send with server in polling mode"""
    _setup(rocev2_env)
    _run_test(rocev2_env, "poll", "[Polling Mode] Received data: Hello RDMA")


def test_rdma_send_event(rocev2_env):
    """Test RDMA send with server in event-driven mode"""
    _setup(rocev2_env)
    _run_test(rocev2_env, "event", "[Event-Driven] Received data: Hello RDMA")


def test_rdma_send_hybrid(rocev2_env):
    """Test RDMA send with server in hybrid mode"""
    _setup(rocev2_env)
    _run_test(rocev2_env, "hybrid", "Received data: Hello RDMA")


def test_rdma_send_poll_trace_event(rocev2_env):
    """Test RDMA send (polling mode) with trace-cmd event recording"""
    _setup(rocev2_env)
    _run_test_with_trace_event(rocev2_env, "poll", "[Polling Mode] Received data: Hello RDMA")


def test_rdma_send_event_trace_event(rocev2_env):
    """Test RDMA send (event-driven mode) with trace-cmd event recording"""
    _setup(rocev2_env)
    _run_test_with_trace_event(rocev2_env, "event", "[Event-Driven] Received data: Hello RDMA")


def test_rdma_send_hybrid_trace_event(rocev2_env):
    """Test RDMA send (hybrid mode) with trace-cmd event recording"""
    _setup(rocev2_env)
    _run_test_with_trace_event(rocev2_env, "hybrid", "Received data: Hello RDMA")


def test_rdma_send_poll_trace_func(rocev2_env):
    """Test RDMA send (polling mode) with trace-cmd function_graph recording"""
    _setup(rocev2_env)
    _run_test_with_trace_func(rocev2_env, "poll", "[Polling Mode] Received data: Hello RDMA")


def test_rdma_send_event_trace_func(rocev2_env):
    """Test RDMA send (event-driven mode) with trace-cmd function_graph recording"""
    _setup(rocev2_env)
    _run_test_with_trace_func(rocev2_env, "event", "[Event-Driven] Received data: Hello RDMA")


def test_rdma_send_hybrid_trace_func(rocev2_env):
    """Test RDMA send (hybrid mode) with trace-cmd function_graph recording"""
    _setup(rocev2_env)
    _run_test_with_trace_func(rocev2_env, "hybrid", "Received data: Hello RDMA")


def _run_test_with_latency(rocev2_env, mode, server_assert):
    """Run RDMA send test, return client-side latency in us."""
    server_ip = rocev2_env.Server.get_ipv4()
    log_suffix = f"rdma_send_{mode}"
    server_log = f"/tmp/{log_suffix}_server.log"
    client_log = f"/tmp/{log_suffix}_client.log"

    # Start server in background
    server_proc = rocev2_env.Server.run(
        f"{BIN_SERVER} --mode {mode} > {server_log} 2>&1",
        background=True
    )
    time.sleep(2)

    try:
        rocev2_env.Client.run(
            f"timeout {TIMEOUT} {BIN_CLIENT} --mode {mode} {server_ip} > {client_log} 2>&1",
            check=False
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

    # Verify RDMA data transfer succeeded
    server_result = rocev2_env.Server.run(f"cat {server_log}", check=False)
    client_result = rocev2_env.Client.run(f"cat {client_log}", check=False)
    assert server_assert in server_result.stdout, \
        f"Server ({mode}) did not receive expected message"
    assert "Data sent successfully" in client_result.stdout, \
        f"Client ({mode}) did not report send success"

    # Parse client latency from stdout: "(latency: N us)"
    import re
    m = re.search(r'\(latency:\s*(\d+)\s*us\)', client_result.stdout)
    return int(m.group(1)) if m else None


def test_rdma_send_latency_compare(rocev2_env):
    """Compare client-side completion latency across poll/event/hybrid modes."""
    _setup(rocev2_env)

    modes = [
        ("poll", "[Polling Mode] Received data: Hello RDMA"),
        ("event", "[Event-Driven] Received data: Hello RDMA"),
        ("hybrid", "Received data: Hello RDMA"),
    ]

    results = {}
    for mode, server_assert in modes:
        results[mode] = _run_test_with_latency(rocev2_env, mode, server_assert)

    print(f"\n=== Latency Comparison (client, us) ===")
    print(f"{'Mode':<10} {'Latency (us)':<14}")
    print("-" * 24)
    for mode in ["poll", "event", "hybrid"]:
        val = results[mode]
        v_str = str(val) if val is not None else "N/A"
        print(f"{mode:<10} {v_str:<14}")


def _run_perf_stat(rocev2_env, mode, server_assert):
    """Run RDMA send with perf stat on both sides, return parsed counters."""
    server_ip = rocev2_env.Server.get_ipv4()
    log_suffix = f"rdma_send_{mode}"
    server_log = f"/tmp/{log_suffix}_server.log"
    client_log = f"/tmp/{log_suffix}_client.log"
    server_perf = f"/tmp/{log_suffix}_server.perf"
    client_perf = f"/tmp/{log_suffix}_client.perf"

    # Start server with perf stat
    server_proc = rocev2_env.Server.run(
        f"perf stat -e cpu-migrations,task-clock,cycles,instructions,bus-cycles "
        f"{BIN_SERVER} --mode {mode} > {server_log} 2> {server_perf}",
        background=True
    )
    time.sleep(2)

    try:
        rocev2_env.Client.run(
            f"perf stat -e cpu-migrations,task-clock,cycles,instructions,bus-cycles "
            f"timeout {TIMEOUT} {BIN_CLIENT} --mode {mode} {server_ip} > {client_log} 2> {client_perf}",
            check=False
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

    # Verify RDMA data transfer succeeded
    server_result = rocev2_env.Server.run(f"cat {server_log}", check=False)
    client_result = rocev2_env.Client.run(f"cat {client_log}", check=False)
    assert server_assert in server_result.stdout, \
        f"Server ({mode}) did not receive expected message"
    assert "Data sent successfully" in client_result.stdout, \
        f"Client ({mode}) did not report send success"

    server_perf_text = rocev2_env.Server.run(f"cat {server_perf}", check=False).stdout
    client_perf_text = rocev2_env.Client.run(f"cat {client_perf}", check=False).stdout

    return {
        "server": parse_perf_stat_text(server_perf_text),
        "client": parse_perf_stat_text(client_perf_text),
    }


def test_rdma_send_perf_stat(rocev2_env):
    """Compare perf stat counters across poll/event/hybrid modes."""
    _setup(rocev2_env)

    modes = [
        ("poll", "[Polling Mode] Received data: Hello RDMA"),
        ("event", "[Event-Driven] Received data: Hello RDMA"),
        ("hybrid", "Received data: Hello RDMA"),
    ]

    results = {}
    for mode, server_assert in modes:
        results[mode] = _run_perf_stat(rocev2_env, mode, server_assert)

    # Print table 1: core counters + IPC
    header1 = (f"{'Mode':<10} {'Side':<8} {'CPU Migr':<10} {'Task Clock (ms)':<16} "
               f"{'Cycles':<14} {'Instructions':<16} {'Bus Cycles':<14} {'IPC':<10}")
    sep1 = "-" * len(header1)
    lines1 = [f"\n=== Perf Stat — Core Counters ===", header1, sep1]

    # Print table 2: time breakdown
    header2 = (f"{'Mode':<10} {'Side':<8} {'User (ms)':<14} {'Sys (ms)':<14} {'Elapsed (ms)':<16}")
    sep2 = "-" * len(header2)
    lines2 = [f"\n=== Perf Stat — Time Breakdown ===", header2, sep2]

    for mode in ["poll", "event", "hybrid"]:
        for side in ["server", "client"]:
            m = results[mode][side]

            # Common value helpers
            _cpu = str(m.get('cpu_migrations', 'N/A')) if m.get('cpu_migrations') is not None else "N/A"
            _tck = f"{m['task_clock']:.3f}" if 'task_clock' in m else "N/A"
            _cyc = str(m.get('cycles', 'N/A'))
            _ins = str(m.get('instructions', 'N/A'))
            _bus = str(m.get('bus_cycles', 'N/A'))
            # IPC = instructions / cycles
            cyc_val = m.get('cycles', 0)
            ins_val = m.get('instructions', 0)
            if isinstance(cyc_val, (int, float)) and isinstance(ins_val, (int, float)) and cyc_val > 0:
                _ipc = f"{ins_val / cyc_val:.4f}"
            else:
                _ipc = "N/A"

            _usr = f"{m['user_time'] * 1000:.3f}" if 'user_time' in m else "N/A"
            _sys = f"{m['sys_time'] * 1000:.3f}" if 'sys_time' in m else "N/A"
            _elp = f"{m['time_elapsed'] * 1000:.3f}" if 'time_elapsed' in m else "N/A"

            lines1.append(f"{mode:<10} {side:<8} {_cpu:<10} {_tck:<16} {_cyc:<14} {_ins:<16} {_bus:<14} {_ipc:<10}")
            lines2.append(f"{mode:<10} {side:<8} {_usr:<14} {_sys:<14} {_elp:<16}")

    for line in lines1:
        print(line)
    for line in lines2:
        print(line)


def _run_perf_record(rocev2_env, mode, server_assert):
    """Run RDMA send under perf record on both sides, return hotspot data."""
    server_ip = rocev2_env.Server.get_ipv4()
    log_suffix = f"rdma_send_{mode}"
    server_log = f"/tmp/{log_suffix}_server.log"
    client_log = f"/tmp/{log_suffix}_client.log"
    server_perf_data = f"/tmp/perf_data_{log_suffix}_server.data"
    client_perf_data = f"/tmp/perf_data_{log_suffix}_client.data"

    # Start server with perf record
    server_proc = rocev2_env.Server.run(
        f"perf record -F 4000 -g -o {server_perf_data} "
        f"{BIN_SERVER} --mode {mode} > {server_log} 2>&1",
        background=True
    )
    time.sleep(2)

    try:
        rocev2_env.Client.run(
            f"perf record -F 4000 -g -o {client_perf_data} "
            f"timeout {TIMEOUT} {BIN_CLIENT} --mode {mode} {server_ip} "
            f"> {client_log} 2>&1",
            check=False
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

    # Verify RDMA data transfer succeeded
    server_result = rocev2_env.Server.run(f"cat {server_log}", check=False)
    client_result = rocev2_env.Client.run(f"cat {client_log}", check=False)
    assert server_assert in server_result.stdout, \
        f"Server ({mode}) did not receive expected message"
    assert "Data sent successfully" in client_result.stdout, \
        f"Client ({mode}) did not report send success"

    # Parse and return hotspot data
    server_hotspots = parse_perf_report(rocev2_env.Server, server_perf_data)
    client_hotspots = parse_perf_report(rocev2_env.Client, client_perf_data)

    return {
        "server": server_hotspots,
        "client": client_hotspots,
    }


def test_rdma_send_perf_hotspot(rocev2_env):
    """Hotspot function analysis for RDMA send across poll/event/hybrid modes."""
    _setup(rocev2_env)

    rocev2_env.Client.run("mkdir -p /tmp/perf_data")
    rocev2_env.Server.run("mkdir -p /tmp/perf_data")

    modes = [
        ("poll", "[Polling Mode] Received data: Hello RDMA"),
        ("event", "[Event-Driven] Received data: Hello RDMA"),
        ("hybrid", "Received data: Hello RDMA"),
    ]

    for mode, server_assert in modes:
        print(f"\n--- Testing Mode: {mode} ---")
        hotspots = _run_perf_record(rocev2_env, mode, server_assert)

        print(f"\n{'='*60}")
        print(f"Hotspot Functions Analysis ({mode}):")
        print(f"{'='*60}")
        print_hotspot_report(hotspots["server"], f"Server Hotspots ({mode})")
        print_hotspot_report(hotspots["client"], f"Client Hotspots ({mode})")
