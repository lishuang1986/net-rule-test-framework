# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
from framework.helpers import is_100_percent_loss


@pytest.mark.netfilter
def test_nft_match_meta_cgroupv2_ipv4(host_router_env):
    """Verify nftables cgroupv2 match drops ICMP echo-request on OUTPUT chain (IPv4)

    Steps (mirroring manual test sequence):
      1. Create cgroup /sys/fs/cgroup/test
      2. Add nftables table and OUTPUT chain (no drop rule yet)
      3. Verify baseline connectivity with a ping (should succeed)
      4. Add nftables drop rule on OUTPUT chain that matches socket
         cgroupv2 /test and drops ICMP echo-request
      5. Run ping from Router (host) inside the cgroup via cgexec
      6. Assert 100% packet loss
      7. Clean up nftables table and cgroup
    """
    infra = host_router_env
    server_ipv4 = infra.Server.get_ipv4()

    # --- Setup ---

    # 1. Create cgroup
    infra.Router.run("mkdir -p /sys/fs/cgroup/test")

    # 2. Add nftables table and OUTPUT chain
    infra.Router.run("nft add table ip filter")
    infra.Router.run(
        "nft add chain ip filter output "
        "{ type filter hook output priority 0 \\; }"
    )

    # 3. Verify baseline connectivity before drop rule takes effect
    infra.Router.run(f"ping -c 1 -W 2 {server_ipv4}")

    # 4. Add drop rule with cgroupv2 match
    infra.Router.run(
        'nft add rule ip filter output '
        'socket cgroupv2 level 1 \\"/test\\" '
        'icmp type echo-request counter drop'
    )

    # --- Test ---

    # 5. Run ping from Router (host) inside the test cgroup
    result = infra.Router.run(
        f"cgexec -g cpu,memory:test ping -c 3 -W 2 {server_ipv4}",
        expect="failed",
    )
    assert is_100_percent_loss(result.stdout + result.stderr)

    # --- Cleanup ---
    infra.Router.run("nft delete table ip filter")

    # Move lingering pids back to root cgroup before rmdir
    infra.Router.run(
        "while read pid; do "
        "echo $pid > /sys/fs/cgroup/cgroup.procs 2>/dev/null; "
        "done < /sys/fs/cgroup/test/cgroup.procs"
    )
    infra.Router.run("rmdir /sys/fs/cgroup/test")
