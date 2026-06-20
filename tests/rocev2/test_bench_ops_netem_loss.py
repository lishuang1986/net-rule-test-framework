# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time
from tests.rocev2.utils import parse_ib_write_bw_output, parse_iperf3_output

pytestmark = [pytest.mark.rocev2]


def _run_ib_write_bw(rocev2_env, server_ip: str) -> dict:
    """Run ib_write_bw with 1MB message size, return parsed bandwidth metrics."""
    server_proc = rocev2_env.Server.popen(
        "ib_write_bw -d rxe_server -R -x 1 -s 1048576 "
        "> /tmp/bw_ops_ib_write_bw_server.log 2>&1"
    )
    time.sleep(2)
    try:
        rocev2_env.Client.run(
            f"ib_write_bw -d rxe_client -R -x 1 -s 1048576 {server_ip} "
            f"> /tmp/bw_ops_ib_write_bw_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

    return parse_ib_write_bw_output(
        rocev2_env.Client, "/tmp/bw_ops_ib_write_bw_client.log"
    )


def _run_ib_read_bw(rocev2_env, server_ip: str) -> dict:
    """Run ib_read_bw with 1MB message size, return parsed bandwidth metrics."""
    server_proc = rocev2_env.Server.popen(
        "ib_read_bw -d rxe_server -R -x 1 -s 1048576 "
        "> /tmp/bw_ops_ib_read_bw_server.log 2>&1"
    )
    time.sleep(2)
    try:
        rocev2_env.Client.run(
            f"ib_read_bw -d rxe_client -R -x 1 -s 1048576 {server_ip} "
            f"> /tmp/bw_ops_ib_read_bw_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

    return parse_ib_write_bw_output(
        rocev2_env.Client, "/tmp/bw_ops_ib_read_bw_client.log"
    )


def _run_ib_send_bw(rocev2_env, server_ip: str) -> dict:
    """Run ib_send_bw with 1MB message size, return parsed bandwidth metrics."""
    server_proc = rocev2_env.Server.popen(
        "ib_send_bw -d rxe_server -R -x 1 -s 1048576 "
        "> /tmp/bw_ops_ib_send_bw_server.log 2>&1"
    )
    time.sleep(2)
    try:
        rocev2_env.Client.run(
            f"ib_send_bw -d rxe_client -R -x 1 -s 1048576 {server_ip} "
            f"> /tmp/bw_ops_ib_send_bw_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

    return parse_ib_write_bw_output(
        rocev2_env.Client, "/tmp/bw_ops_ib_send_bw_client.log"
    )


def _run_iperf3_tcp(rocev2_env, server_ip: str) -> dict:
    """Run iperf3 TCP test for 10 seconds, return bandwidth metrics.

    Returns a dict with keys matching parse_ib_write_bw_output convention
    (bw_avg_mb_sec, bw_peak_mb_sec) for table uniformity.
    """
    port = 5202
    server_proc = rocev2_env.Server.popen(
        f"iperf3 -s -p {port} --one-off "
        f"> /tmp/bw_ops_iperf3_server.log 2>&1"
    )
    time.sleep(1)
    try:
        rocev2_env.Client.run(
            f"iperf3 -c {server_ip} -p {port} -f m "
            f"> /tmp/bw_ops_iperf3_client.log 2>&1"
        )
    finally:
        server_proc.terminate()
        server_proc.wait()

    return parse_iperf3_output(
        rocev2_env.Client, "/tmp/bw_ops_iperf3_client.log"
    )


def test_bench_ops_netem_loss(rocev2_env):
    """Benchmark and compare bandwidth across operations under different netem loss rates.

    Runs all four operations under 0%, 0.1%, and 0.5% netem packet loss on the
    client egress. Prints a comparison table showing bandwidth and degradation
    percentage for each loss rate.
    """
    server_ip = rocev2_env.Server.get_ipv4()
    client_iface = rocev2_env.Client.get_iface()

    ops = [
        ("ib_write_bw", _run_ib_write_bw),
        ("ib_read_bw",  _run_ib_read_bw),
        ("ib_send_bw",  _run_ib_send_bw),
        ("iperf3 tcp",  _run_iperf3_tcp),
    ]

    loss_rates = [0.0, 0.1, 0.5]  # percentage
    results = {}  # loss_pct -> {op_name -> bw_data}

    netem_applied = False
    try:
        for loss_pct in loss_rates:
            # Set up netem (skip for 0% baseline)
            if loss_pct > 0:
                if not netem_applied:
                    rocev2_env.Client.run(
                        f"tc qdisc add dev {client_iface} root netem loss {loss_pct}%"
                    )
                    netem_applied = True
                else:
                    rocev2_env.Client.run(
                        f"tc qdisc change dev {client_iface} root netem loss {loss_pct}%"
                    )

            loss_label = "no loss" if loss_pct == 0 else f"{loss_pct}% loss"
            for op_name, runner in ops:
                print(f"\n--- Testing {op_name} ({loss_label}) ---")
                results.setdefault(loss_pct, {})[op_name] = runner(rocev2_env, server_ip)

                d = results[loss_pct][op_name]
                bw_avg = d.get('bw_avg_mb_sec', 0)
                bw_peak = d.get('bw_peak_mb_sec', 0)
                iters = d.get('iterations', 'N/A')
                print(f"  Iterations: {iters}, BW avg: {bw_avg:.2f} MB/sec, "
                      f"BW peak: {bw_peak:.2f} MB/sec")
    finally:
        if netem_applied:
            rocev2_env.Client.run(f"tc qdisc del dev {client_iface} root")

    # ==============================================
    # Bandwidth comparison table
    # ==============================================
    loss_labels = [f"NoLoss" if r == 0 else f"{r}%" for r in loss_rates]
    col_w = 12
    degrad_w = 8

    # Header row (compute actual width for separator line)
    h  = f"{'Operation':<14}"
    for label in loss_labels:
        h += f"  {label + ' avg':<{col_w}}"
    for i, label in enumerate(loss_labels):
        if i > 0:
            h += f"  {'Degr@' + label:<{degrad_w}}"
    table_w = len(h)
    sep = "=" * table_w
    print(f"\n{sep}")
    title = f"Bandwidth Comparison: {' vs '.join(loss_labels)} netem loss (1MB message)"
    print(title)
    print(sep)

    # Print header row
    print(h)
    sep2 = "-" * table_w
    print(sep2)

    # Data rows
    for op_name in [o[0] for o in ops]:
        row  = f"{op_name:<14}"
        d0 = results[loss_rates[0]][op_name]
        a0 = d0.get('bw_avg_mb_sec', 0)
        for loss_pct in loss_rates:
            d = results[loss_pct][op_name]
            _avg = (f"{d['bw_avg_mb_sec']:.2f} MB/s"
                    if d.get('bw_avg_mb_sec') else 'N/A')
            row += f"  {_avg:<{col_w}}"
        for i, loss_pct in enumerate(loss_rates):
            if i == 0:
                continue
            d = results[loss_pct][op_name]
            a1 = d.get('bw_avg_mb_sec', 0)
            if a0 and a1:
                degrad = f"{(a0 - a1) / a0 * 100:.1f}%"
            else:
                degrad = "N/A"
            row += f"  {degrad:<{degrad_w}}"
        print(row)
    print(sep)
