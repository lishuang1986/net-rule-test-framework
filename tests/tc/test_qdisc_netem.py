# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import re
import pytest
from scipy import stats
from framework.helpers import get_avg_rtt


@pytest.mark.tc
def test_qdisc_netem_client_server(client_server_env):
    infra = client_server_env
    
    iface = infra.Client.get_iface()
    infra.Client.run(f"tc qdisc add dev {iface} root netem delay 100ms")
    
    result = infra.Client.run(f"ping -c 5 -W 2 {infra.Server.get_ipv4()}")
    
    avg_rtt = get_avg_rtt(result.stdout)
    if avg_rtt > 0:
        assert avg_rtt >= 100
    
    infra.Client.run(f"tc qdisc del dev {iface} root")


@pytest.mark.tc
def test_qdisc_netem_on_router(router_env):
    infra = router_env
    
    iface = infra.Router.get_iface_to_server()
    infra.Router.run(f"tc qdisc add dev {iface} root netem delay 100ms")
    
    result = infra.Client.run(f"ping -c 5 -W 2 {infra.Server.get_ipv4()}")
    
    avg_rtt = get_avg_rtt(result.stdout)
    if avg_rtt > 0:
        assert avg_rtt >= 100
    
    infra.Router.run(f"tc qdisc del dev {iface} root")


@pytest.mark.tc
def test_qdisc_netem_loss(client_server_env):
    """Benchmark netem packet loss rates: 10%, 1%, 0.1%, 0.01%.

    Runs each loss rate 10 times with flood ping, prints per-iteration
    detail, then performs a one-sample T-test (H0: mean lost == expected)
    at alpha=0.01 for each rate.
    """
    infra = client_server_env
    iface = infra.Client.get_iface()
    server_ip = infra.Server.get_ipv4()

    # (label, ping count)
    loss_configs = [
        ("10%", 3000),
        ("1%", 10000),
        ("0.1%", 100000),
        ("0.01%", 100000),
    ]

    all_results = {}  # label -> [(tx, rx, lost, loss%), ...]

    for label, count in loss_configs:
        infra.Client.run(f"tc qdisc add dev {iface} root netem loss {label}")

        run_data = []
        try:
            for i in range(10):
                result = infra.Client.run(f"ping -f -c {count} {server_ip}")

                tx_match = re.search(r"(\d+) packets transmitted", result.stdout)
                rx_match = re.search(r"(\d+) received", result.stdout)
                loss_match = re.search(r"(\d+(?:\.\d+)?)% packet loss", result.stdout)

                tx = int(tx_match.group(1)) if tx_match else 0
                rx = int(rx_match.group(1)) if rx_match else 0
                actual_loss = float(loss_match.group(1)) if loss_match else 100.0

                run_data.append((tx, rx, tx - rx, actual_loss))
        finally:
            infra.Client.run(f"tc qdisc del dev {iface} root")

        all_results[label] = run_data

    # =========================================
    # Per-iteration detail
    # =========================================
    for label, run_data in all_results.items():
        print(f"\n{'=' * 60}")
        print(f"  netem loss: {label} (10 iterations)")
        print(f"{'=' * 60}")
        for i, (tx, rx, lost, loss_pct) in enumerate(run_data, 1):
            print(f"  Run {i:2d}: Tx={tx}, Rx={rx}, Lost={lost}, Loss={loss_pct}%")

    # =========================================
    # One-sample T-test
    # =========================================
    alpha = 0.01
    errors = []
    print(f"\n{'=' * 70}")
    print(f"One-sample T-test   H0: mean(Lost) = expected (alpha={alpha})")
    print(f"{'=' * 70}")
    h = f"{'Loss':<10} {'Expected':<10} {'Mean Lost':<12} {'t':<10} {'p-value':<12} {'Result':<10}"
    print(h)
    print("-" * len(h))
    for label, run_data in all_results.items():
        pct = float(label.rstrip('%')) / 100.0
        count = next(c for l, c in loss_configs if l == label)
        expected = pct * count

        lost_values = [d[2] for d in run_data]
        mean_lost = sum(lost_values) / len(lost_values)
        t_stat, p_value = stats.ttest_1samp(lost_values, expected)

        status = "REJECT" if p_value < alpha else "OK"
        print(f"{label:<10} {expected:<10.1f} {mean_lost:<12.2f} {t_stat:<10.4f} {p_value:<12.6f} {status:<10}")
        if p_value < alpha:
            errors.append(
                f"  {label}: mean lost={mean_lost:.2f} != expected={expected:.1f} "
                f"(t={t_stat:.4f}, p={p_value:.6f})"
            )
    print(f"{'=' * 70}")
    if errors:
        raise AssertionError(
            "T-test rejected H0 for the following loss rates:\n" + "\n".join(errors)
        )
