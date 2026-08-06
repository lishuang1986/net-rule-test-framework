# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import time
import pytest

pytestmark = [pytest.mark.tc]


def test_tcp_ecn_handshake_client_server(client_server_env):
    """Experiment 1: TCP ECN handshake negotiation (client-server topology).

    Client and server are directly connected; ECN negotiation is
    end-to-end between client and server.

    Steps:
      1. Enable tcp_ecn=1 on both client and server namespaces
      2. Start ncat server on server port 8080
      3. Client sends "hello world" via ncat
      4. Capture TCP handshake with tcpdump and verify ECN flags (ECE/CWR)
    """
    infra = client_server_env
    server_ip = infra.Server.get_ipv4()

    ecn_original = {}
    server_proc = None
    tcpdump_proc = None

    try:
        # Step 1: Enable TCP ECN on both sides, save original values
        for side, label in [(infra.Client, "Client"), (infra.Server, "Server")]:
            result = side.run("sysctl -n net.ipv4.tcp_ecn")
            ecn_original[label] = result.stdout.strip()
            side.run("sysctl -w net.ipv4.tcp_ecn=1")

        # Step 2: Start ncat server in background (listen, recv-only, with sh-exec + -o)
        server_proc = infra.Server.popen(
            f"ncat -4 --recv-only {server_ip} 8080 -l -k --sh-exec cat "
            "-o /tmp/ecn_test_recv.log 2>&1"
        )
        time.sleep(1)

        # Step 2.5: Start tcpdump on client interface to capture TCP handshake
        infra.Client.run("rm -f /tmp/ecn_handshake.pcap")
        client_iface = infra.Client.get_iface()
        tcpdump_proc = infra.Client.popen(
            f"tcpdump -U -i {client_iface} port 8080 "
            f"-w /tmp/ecn_handshake.pcap 2>&1"
        )
        time.sleep(1)

        # Step 3: Client connects and sends "hello world"
        infra.Client.run(
            f"echo 'hello world' | ncat -4 --send-only {server_ip} 8080"
        )
        time.sleep(1)

        # Step 4: Stop tcpdump and observe ECN negotiation
        tcpdump_proc.terminate()
        tcpdump_proc.wait()
        tcpdump_proc = None
        time.sleep(1)

        infra.Client.run(r"tshark -r /tmp/ecn_handshake.pcap | grep '\[SYN, ECE, CWR\]'")
        infra.Client.run(r"tshark -r /tmp/ecn_handshake.pcap | grep '\[SYN, ACK, ECE\]'")
        infra.Client.run("tshark -r /tmp/ecn_handshake.pcap -O ip")

    finally:
        # Terminate tcpdump if still running
        if tcpdump_proc is not None:
            tcpdump_proc.terminate()
            tcpdump_proc.wait()

        # Terminate server process
        if server_proc is not None:
            server_proc.terminate()
            server_proc.wait()

        # Restore original tcp_ecn values
        for side, label in [(infra.Client, "Client"), (infra.Server, "Server")]:
            orig = ecn_original.get(label, "0")
            side.run(f"sysctl -w net.ipv4.tcp_ecn={orig}")


def _run_iperf3_tcp(infra, server_ip: str, port: int,
                    tcpdump_filter: str | None = None,
                    pcap_path: str = "/tmp/red_ecn_iperf3.pcap") -> str:
    """Run one iperf3 TCP test, optionally capture ECN-marked packets mid-run."""
    server_proc = infra.Server.popen(f"iperf3 -s -p {port} --one-off ")
    time.sleep(1)
    try:
        client_proc = infra.Client.popen(f"iperf3 -c {server_ip} -p {port} -f m -P 8")
        time.sleep(5)
        infra.Client.run(f"ss -ti | grep -E 'rtt:|{port}'", check=False)
        if tcpdump_filter is not None:
            infra.Server.run(f"rm -f {pcap_path}")
            infra.Server.run(
                f"timeout 5 tcpdump -U -i {infra.Server.get_iface()} -c 10 "
                f"'{tcpdump_filter}' -w {pcap_path}")
            infra.Server.run(f"tshark -r {pcap_path} -c 1 -O ip")
        stdout, _ = client_proc.communicate()
    finally:
        server_proc.terminate()
        server_proc.wait()
    return stdout.decode()


def test_qdisc_red_perf_comparison(client_server_env):
    """Compare iperf3 TCP bandwidth across three qdisc modes on the same tbf
    shaper: baseline (tbf only), tbf+red(drop), and tbf+red(mark/ECN).

    Captures ECT packets (baseline/drop) and CE-marked packets (mark) per mode
    to verify how RED behaves; bandwidth degradation is the main metric.
    """
    infra = client_server_env
    server_ip = infra.Server.get_ipv4()
    client_iface = infra.Client.get_iface()
    port = 5202

    ecn_original = {}

    # (label, red_extra, tcpdump_filter, pcap_path)
    # red_extra: extra tc-red args after the base params; None = no RED child.
    #   ""      -> plain RED, drops packets
    #   "ecn"   -> RED marks CE instead of dropping
    modes = [
        ("Baseline (tbf only, no RED)", None,
         "ip[1] & 0x03 != 0", "/tmp/red_ecn_baseline.pcap"),
        ("tbf + red (drop)", "",
         "ip[1] & 0x03 != 0", "/tmp/red_ecn_drop.pcap"),
        ("tbf + red (mark)", "ecn",
         "ip[1] & 0x03 == 0x03", "/tmp/red_ecn_mark.pcap"),
    ]

    try:
        # Save & set ECN on both sides
        for side, label in [(infra.Client, "Client"), (infra.Server, "Server")]:
            result = side.run("sysctl -n net.ipv4.tcp_ecn")
            ecn_original[label] = result.stdout.strip()
            side.run("sysctl -w net.ipv4.tcp_ecn=1")

        for label, red_extra, filter_, pcap in modes:
            # Reset root qdisc, then add the same tbf shaper in every mode
            infra.Client.run(f"tc qdisc del dev {client_iface} root", check=False)
            infra.Client.run(f"tc qdisc add dev {client_iface} root handle 1: tbf "
                             f"rate 10gbit burst 1600kb latency 50ms")
            if red_extra is not None:
                red_cmd = (f"tc qdisc add dev {client_iface} parent 1: handle 2: red "
                           f"limit 2400000 min 200000 max 600000 avpkt 1000 "
                           f"burst 333 bandwidth 10000Mbit probability 0.01")
                if red_extra:
                    red_cmd += f" {red_extra}"
                infra.Client.run(red_cmd)

            print(f"=== {label} ===")
            print(_run_iperf3_tcp(infra, server_ip, port,
                                  tcpdump_filter=filter_,
                                  pcap_path=pcap))

    finally:
        infra.Client.run(f"tc qdisc del dev {client_iface} root", check=False)
        for side, label in [(infra.Client, "Client"), (infra.Server, "Server")]:
            orig = ecn_original.get(label, "0")
            side.run(f"sysctl -w net.ipv4.tcp_ecn={orig}")
