# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
import time
from tests.rocev2.utils import parse_ib_write_bw_output, parse_iperf3_output

pytestmark = [pytest.mark.rocev2]


def _run_ib_write_bw(rocev2_env, server_ip: str,
                     tcpdump_filter: str | None = None,
                     pcap_path: str = "/tmp/bw_ops_ib_write_bw.pcap") -> dict:
    """Run ib_write_bw with 1MB message size, return parsed bandwidth metrics.

    Optionally capture ECN-marked RoCE packets with a background tcpdump while
    the op runs.
    """
    server_proc = rocev2_env.Server.popen(
        "ib_write_bw -d rxe_server -R -x 1 "
        "> /tmp/bw_ops_ib_write_bw_server.log 2>&1"
    )
    time.sleep(2)
    client_cmd = (f"ib_write_bw -d rxe_client -R -x 1 {server_ip} "
                  f"> /tmp/bw_ops_ib_write_bw_client.log 2>&1")
    tcpdump_proc = None
    try:
        if tcpdump_filter is not None:
            rocev2_env.Server.run(f"rm -f {pcap_path}")
            tcpdump_proc = rocev2_env.Server.popen(
                f"timeout 10 tcpdump -U -i {rocev2_env.Server.get_iface()} -c 10 "
                f"'{tcpdump_filter}' -w {pcap_path} 2>&1"
            )
            time.sleep(1)
        rocev2_env.Client.run(client_cmd)
    finally:
        if tcpdump_proc is not None:
            tcpdump_proc.terminate()
            tcpdump_proc.wait()
        server_proc.terminate()
        server_proc.wait()

    if tcpdump_filter is not None:
        # Print the captured RoCE packets after tcpdump has stopped.
        rocev2_env.Server.run(f"tshark -r {pcap_path}", check=False)
        rocev2_env.Server.run(f"tshark -r {pcap_path} -c 1 -O ip", check=False)

    return parse_ib_write_bw_output(
        rocev2_env.Client, "/tmp/bw_ops_ib_write_bw_client.log"
    )


def _run_ib_read_bw(rocev2_env, server_ip: str,
                    tcpdump_filter: str | None = None,
                    pcap_path: str = "/tmp/bw_ops_ib_read_bw.pcap") -> dict:
    """Run ib_read_bw with 1MB message size, return parsed bandwidth metrics.

    Optionally capture ECN-marked RoCE packets with a background tcpdump while
    the op runs.
    """
    server_proc = rocev2_env.Server.popen(
        "ib_read_bw -d rxe_server -R -x 1 "
        "> /tmp/bw_ops_ib_read_bw_server.log 2>&1"
    )
    time.sleep(2)
    client_cmd = (f"ib_read_bw -d rxe_client -R -x 1 {server_ip} "
                  f"> /tmp/bw_ops_ib_read_bw_client.log 2>&1")
    tcpdump_proc = None
    try:
        if tcpdump_filter is not None:
            rocev2_env.Server.run(f"rm -f {pcap_path}")
            tcpdump_proc = rocev2_env.Server.popen(
                f"timeout 10 tcpdump -U -i {rocev2_env.Server.get_iface()} -c 10 "
                f"'{tcpdump_filter}' -w {pcap_path} 2>&1"
            )
            time.sleep(1)
        rocev2_env.Client.run(client_cmd)
    finally:
        if tcpdump_proc is not None:
            tcpdump_proc.terminate()
            tcpdump_proc.wait()
        server_proc.terminate()
        server_proc.wait()

    if tcpdump_filter is not None:
        # Print the captured RoCE packets after tcpdump has stopped.
        rocev2_env.Server.run(f"tshark -r {pcap_path}", check=False)
        rocev2_env.Server.run(f"tshark -r {pcap_path} -c 1 -O ip", check=False)

    return parse_ib_write_bw_output(
        rocev2_env.Client, "/tmp/bw_ops_ib_read_bw_client.log"
    )


def _run_ib_send_bw(rocev2_env, server_ip: str,
                    tcpdump_filter: str | None = None,
                    pcap_path: str = "/tmp/bw_ops_ib_send_bw.pcap") -> dict:
    """Run ib_send_bw with 1MB message size, return parsed bandwidth metrics.

    Optionally capture ECN-marked RoCE packets with a background tcpdump while
    the op runs.
    """
    server_proc = rocev2_env.Server.popen(
        "ib_send_bw -d rxe_server -R -x 1 "
        "> /tmp/bw_ops_ib_send_bw_server.log 2>&1"
    )
    time.sleep(2)
    client_cmd = (f"ib_send_bw -d rxe_client -R -x 1 {server_ip} "
                  f"> /tmp/bw_ops_ib_send_bw_client.log 2>&1")
    tcpdump_proc = None
    try:
        if tcpdump_filter is not None:
            rocev2_env.Server.run(f"rm -f {pcap_path}")
            tcpdump_proc = rocev2_env.Server.popen(
                f"timeout 10 tcpdump -U -i {rocev2_env.Server.get_iface()} -c 10 "
                f"'{tcpdump_filter}' -w {pcap_path} 2>&1"
            )
            time.sleep(1)
        rocev2_env.Client.run(client_cmd)
    finally:
        if tcpdump_proc is not None:
            tcpdump_proc.terminate()
            tcpdump_proc.wait()
        server_proc.terminate()
        server_proc.wait()

    if tcpdump_filter is not None:
        # Print the captured RoCE packets after tcpdump has stopped.
        rocev2_env.Server.run(f"tshark -r {pcap_path}", check=False)
        rocev2_env.Server.run(f"tshark -r {pcap_path} -c 1 -O ip", check=False)

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


def _print_bw_comparison_table(ops, scenario_labels, results, title):
    """Print a bandwidth comparison table.

    Args:
        ops: list of (op_name, runner) tuples
        scenario_labels: scenario names, first one is the baseline
        results: dict[scenario_label][op_name] -> bw_data dict
        title: table title
    """
    col_w = 12
    degrad_w = 8

    h = f"{'Operation':<14}"
    for label in scenario_labels:
        h += f"  {label + ' avg':<{col_w}}"
    for label in scenario_labels[1:]:
        h += f"  {'Degr@' + label:<{degrad_w}}"
    table_w = len(h)
    sep = "=" * table_w
    print(f"\n{sep}")
    print(title)
    print(sep)
    print(h)
    print("-" * table_w)

    for op_name in [o[0] for o in ops]:
        row = f"{op_name:<14}"
        d0 = results[scenario_labels[0]][op_name]
        a0 = d0.get('bw_avg_mb_sec', 0)
        for label in scenario_labels:
            d = results[label][op_name]
            _avg = (f"{d['bw_avg_mb_sec']:.2f} MB/s"
                    if d.get('bw_avg_mb_sec') else 'N/A')
            row += f"  {_avg:<{col_w}}"
        for label in scenario_labels[1:]:
            d = results[label][op_name]
            a1 = d.get('bw_avg_mb_sec', 0)
            if a0 and a1:
                degrad = f"{(a0 - a1) / a0 * 100:.1f}%"
            else:
                degrad = "N/A"
            row += f"  {degrad:<{degrad_w}}"
        print(row)
    print(sep)


def test_bench_bw_qdisc_netem_loss(rocev2_env):
    """Benchmark and compare bandwidth across operations under different netem loss rates.

    Runs all four operations under 0%, 0.1%, and 0.5% netem packet loss on both
    client and server egress. Prints a comparison table showing bandwidth and
    degradation percentage for each loss rate.
    """
    server_ip = rocev2_env.Server.get_ipv4()
    client_iface = rocev2_env.Client.get_iface()
    server_iface = rocev2_env.Server.get_iface()
    nodes = [(rocev2_env.Client, client_iface), (rocev2_env.Server, server_iface)]

    ops = [
        ("ib_write_bw", _run_ib_write_bw),
        ("ib_read_bw",  _run_ib_read_bw),
        ("ib_send_bw",  _run_ib_send_bw),
        ("iperf3 tcp",  _run_iperf3_tcp),
    ]

    loss_rates = [0.0, 0.1, 0.5]  # percentage
    loss_labels = [f"NoLoss" if r == 0 else f"{r}%" for r in loss_rates]
    results = {}  # loss_label -> {op_name -> bw_data}

    netem_applied = False
    try:
        for loss_pct, loss_label in zip(loss_rates, loss_labels):
            # Set up netem on both ends (skip for 0% baseline)
            if loss_pct > 0:
                if not netem_applied:
                    for node, iface in nodes:
                        node.run(
                            f"tc qdisc add dev {iface} root netem loss {loss_pct}%"
                        )
                    netem_applied = True
                else:
                    for node, iface in nodes:
                        node.run(
                            f"tc qdisc change dev {iface} root netem loss {loss_pct}%"
                        )

            for op_name, runner in ops:
                print(f"\n--- Testing {op_name} ({loss_label}) ---")
                results.setdefault(loss_label, {})[op_name] = runner(rocev2_env, server_ip)

                d = results[loss_label][op_name]
                bw_avg = d.get('bw_avg_mb_sec', 0)
                bw_peak = d.get('bw_peak_mb_sec', 0)
                iters = d.get('iterations', 'N/A')
                #print(f"  Iterations: {iters}, BW avg: {bw_avg:.2f} MB/sec, "
                #      f"BW peak: {bw_peak:.2f} MB/sec")
    finally:
        if netem_applied:
            for node, iface in nodes:
                node.run(f"tc qdisc del dev {iface} root", check=False)

    _print_bw_comparison_table(
        ops, loss_labels, results,
        f"Bandwidth Comparison: {' vs '.join(loss_labels)} netem loss (1MB message)",
    )


def test_bench_bw_qdisc_red(rocev2_env):
    """Benchmark bandwidth across operations: tbf-only vs tbf+red on both client
    and server egress.

    Runs all four operations under two qdisc configs and prints a
    comparison table showing bandwidth and degradation percentage.
    """
    server_ip = rocev2_env.Server.get_ipv4()
    client_iface = rocev2_env.Client.get_iface()
    server_iface = rocev2_env.Server.get_iface()
    nodes = [(rocev2_env.Client, client_iface), (rocev2_env.Server, server_iface)]

    ops = [
        ("ib_write_bw", _run_ib_write_bw),
        ("ib_read_bw",  _run_ib_read_bw),
        ("ib_send_bw",  _run_ib_send_bw),
    ]

    # (cfg_name, cmds, tcpdump_filter): drop mode captures ECN-capable (ECT)
    # RoCE packets, mark mode captures CE-marked packets.
    configs = [
        ("drop", [
            "tc qdisc add dev {iface} root handle 1: tbf "
            "rate 10gbit burst 1600kb latency 50ms",
            "tc qdisc add dev {iface} parent 1: handle 2: red "
            "limit 2400000 min 200000 max 600000 avpkt 1000 "
            "burst 333 bandwidth 10000Mbit probability 0.01",
        ], "udp port 4791"),
        ("mark", [
            "tc qdisc del dev {iface} root",
            "tc qdisc add dev {iface} root handle 1: tbf "
            "rate 10gbit burst 1600kb latency 50ms",
            "tc qdisc add dev {iface} parent 1: handle 2: red "
            "limit 2400000 min 200000 max 600000 avpkt 1000 "
            "burst 333 bandwidth 10000Mbit probability 0.01 ecn nodrop",
        ], "udp port 4791"),
    ]

    results = {}  # cfg_name -> {op_name -> bw_data}

    try:
        for cfg_name, cmds, filter_ in configs:
            for cmd in cmds:
                for node, iface in nodes:
                    node.run(cmd.format(iface=iface))

            print(f"\n--- Testing with config: {cfg_name} ---")
            for op_name, runner in ops:
                results.setdefault(cfg_name, {})[op_name] = runner(
                    rocev2_env, server_ip, tcpdump_filter=filter_)
                d = results[cfg_name][op_name]
                bw_avg = d.get('bw_avg_mb_sec', 0)
                bw_peak = d.get('bw_peak_mb_sec', 0)
                iters = d.get('iterations', 'N/A')
                #print(f"  Iterations: {iters}, BW avg: {bw_avg:.2f} MB/sec, "
                #      f"BW peak: {bw_peak:.2f} MB/sec")
    finally:
        for node, iface in nodes:
            node.run(f"tc qdisc del dev {iface} root", check=False)

    cfg_labels = [c[0] for c in configs]
    _print_bw_comparison_table(
        ops, cfg_labels, results,
        f"Bandwidth Comparison: {' vs '.join(cfg_labels)}",
    )
