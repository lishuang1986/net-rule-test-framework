# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import time
import re
import pytest


@pytest.mark.tc
@pytest.mark.parametrize("tc_cmds", [
    pytest.param([
        "tc qdisc add dev {iface} root handle 1: tbf rate 1gbit burst 1600kb latency 50ms",
        "tc qdisc add dev {iface} parent 1: handle 2: ets bands 6 "
        "priomap 1 0 2 0 4 0 3 0 5 5 5 5 5 5 5 5 "
        "quanta 1000 2000 3000 4000 5000 6000",
    ], id="shared"),
    pytest.param([
        "tc qdisc add dev {iface} root handle 1: tbf rate 1gbit burst 1600kb latency 50ms",
        "tc qdisc add dev {iface} parent 1: handle 2: ets bands 6 strict 6 "
        "priomap 1 0 2 0 4 0 3 0 5 5 5 5 5 5 5 5 ",
    ], id="strict"),
])
def test_qdisc_ets_client_server(client_server_env, tc_cmds):
    infra = client_server_env

    iface = infra.Client.get_iface()
    for cmd in tc_cmds:
        infra.Client.run(cmd.format(iface=iface))

    server_proc = infra.Server.popen("netserver -D")
    time.sleep(1)
    client1 = infra.Client.popen(f"netperf -H {infra.Server.get_ipv4()} -Y 0x0")
    client2 = infra.Client.popen(f"netperf -H {infra.Server.get_ipv4()} -Y 0x8")
    client3 = infra.Client.popen(f"netperf -H {infra.Server.get_ipv4()} -Y 0x10")
    client4 = infra.Client.popen(f"netperf -H {infra.Server.get_ipv4()} -Y 0x18")

    for i, proc in enumerate([client1, client2, client3, client4], 1):
        stdout, stderr = proc.communicate()
        print(f"=== netperf-{i} stdout ===")
        print(stdout.decode())
        if stderr:
            print(f"=== netperf-{i} stderr ===")
            print(stderr.decode())

    server_proc.terminate()
    server_proc.wait()

    infra.Client.run(f"tc -s class show dev {iface}")
    infra.Client.run(f"tc qdisc del dev {iface} root")
