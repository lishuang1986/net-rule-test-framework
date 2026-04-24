# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import pytest
from framework.helpers import is_100_percent_loss

@pytest.mark.tc
def test_u32_match_icmp_ipv4(client_server_env):
    """
    Test TC u32 matcher matching ICMP packets and dropping them
    Includes: pass when no match, egress match drop, ingress match drop
    """
    infra = client_server_env

    client_iface = infra.Client.get_iface()
    server_ipv4 = infra.Server.get_ipv4()

    # ============================================================
    # 1. Create clsact qdisc
    # ============================================================
    infra.Client.run(f"tc qdisc add dev {client_iface} clsact")

    # ============================================================
    # 2. When no matching rules, ping should succeed
    # ============================================================
    result = infra.Client.run(f"ping -c 3 -W 2 {server_ipv4}")
    assert not is_100_percent_loss(result.stdout + result.stderr), \
        "Initial ping should succeed (no matching rules)"

    # ============================================================
    # 3. Egress direction: match ICMP echo request (type 8, code 0) and drop
    # ============================================================
    # Create divisor table
    infra.Client.run(
        f"tc filter add dev {client_iface} egress protocol ip handle 1: u32 divisor 1"
    )
    # Add matching rule
    infra.Client.run(
        f"tc filter add dev {client_iface} egress protocol ip u32 ht 1: "
        f"match ip protocol 1 0xff match icmp type 8 0xff match icmp code 0 0xff action drop"
    )
    # Add jump rule
    infra.Client.run(
        f"tc filter add dev {client_iface} egress protocol ip u32 ht 800: "
        f"match ip protocol 1 0xff offset at 0 mask 0x0f00 shift 6 link 1:"
    )

    # Verify egress packet loss
    result = infra.Client.run(f"ping -c 3 -W 2 {server_ipv4}", expect='failed')
    assert is_100_percent_loss(result.stdout + result.stderr), \
        "Should drop packets after egress direction matches ICMP echo request"

    # Show filter status (for debugging)
    infra.Client.run(f"tc -s filter show dev {client_iface} egress")

    infra.Client.run(
        f"tc filter del dev {client_iface} egress"
    )
    # ============================================================
    # 4. Ingress direction: match ICMP echo reply (type 0, code 0) and drop
    # ============================================================
    infra.Client.run(
        f"tc filter add dev {client_iface} ingress protocol ip handle 1: u32 divisor 1"
    )
    infra.Client.run(
        f"tc filter add dev {client_iface} ingress protocol ip u32 ht 1: "
        f"match ip protocol 1 0xff match icmp type 0 0xff match icmp code 0 0xff action drop"
    )
    infra.Client.run(
        f"tc filter add dev {client_iface} ingress protocol ip u32 ht 800: "
        f"match ip protocol 1 0xff offset at 0 mask 0x0f00 shift 6 link 1:"
    )

    # Verify ingress packet loss
    result = infra.Client.run(f"ping -c 3 -W 2 {server_ipv4}", expect='failed')
    assert is_100_percent_loss(result.stdout + result.stderr), \
        "Should drop packets after ingress direction matches ICMP echo reply"

    # Show filter status (for debugging)
    infra.Client.run(f"tc -s filter show dev {client_iface} ingress")

    # ============================================================
    # 5. Cleanup
    # ============================================================
    infra.Client.run(f"tc qdisc del dev {client_iface} clsact")

@pytest.mark.tc
def test_u32_match_icmp_ipv6(client_server_env):
    """
    Test TC u32 matcher matching IPv6 ICMPv6 packets and dropping them
    Includes: pass when no match, egress match drop, ingress match drop
    """
    infra = client_server_env

    client_iface = infra.Client.get_iface()
    server_ipv6 = infra.Server.get_ipv6()

    # ============================================================
    # 1. Create clsact qdisc
    # ============================================================
    infra.Client.run(f"tc qdisc add dev {client_iface} clsact")

    # ============================================================
    # 2. When no matching rules, ping6 should succeed
    # ============================================================
    result = infra.Client.run(f"ping6 -c 3 -W 2 {server_ipv6}")
    assert not is_100_percent_loss(result.stdout + result.stderr), \
        "Initial ping6 should succeed (no matching rules)"

    # ============================================================
    # 3. Egress direction: match ICMPv6 echo request (type 128, code 0) and drop
    # ============================================================
    # Create divisor table
    infra.Client.run(
        f"tc filter add dev {client_iface} egress protocol ipv6 handle 1: u32 divisor 1"
    )
    # Add matching rule
    infra.Client.run(
        f"tc filter add dev {client_iface} egress protocol ipv6 u32 ht 1: "
        f"match ip6 protocol 58 0xff match icmp type 128 0xff match icmp code 0 0xff action drop"
    )
    # Add jump rule
    infra.Client.run(
        f"tc filter add dev {client_iface} egress protocol ipv6 u32 ht 800: "
        f"match ip6 protocol 58 0xff offset plus 40 link 1:"
    )

    # Verify egress packet loss
    result = infra.Client.run(f"ping6 -c 3 -W 2 {server_ipv6}", expect='failed')
    assert is_100_percent_loss(result.stdout + result.stderr), \
        "Should drop packets after egress direction matches ICMPv6 echo request"

    # Show filter status (for debugging)
    infra.Client.run(f"tc -s filter show dev {client_iface} egress")

    infra.Client.run(
        f"tc filter del dev {client_iface} egress"
    )
    # ============================================================
    # 4. Ingress direction: match ICMPv6 echo reply (type 129, code 0) and drop
    # ============================================================
    infra.Client.run(
        f"tc filter add dev {client_iface} ingress protocol ipv6 handle 1: u32 divisor 1"
    )
    infra.Client.run(
        f"tc filter add dev {client_iface} ingress protocol ipv6 u32 ht 1: "
        f"match ip6 protocol 58 0xff match icmp type 129 0xff match icmp code 0 0xff action drop"
    )
    infra.Client.run(
        f"tc filter add dev {client_iface} ingress protocol ipv6 u32 ht 800: "
        f"match ip6 protocol 58 0xff offset plus 40 link 1:"
    )

    # Verify ingress packet loss
    result = infra.Client.run(f"ping6 -c 3 -W 2 {server_ipv6}", expect='failed')
    assert is_100_percent_loss(result.stdout + result.stderr), \
        "Should drop packets after ingress direction matches ICMPv6 echo reply"

    # Show filter status (for debugging)
    infra.Client.run(f"tc -s filter show dev {client_iface} ingress")

    # ============================================================
    # 5. Cleanup
    # ============================================================
    infra.Client.run(f"tc qdisc del dev {client_iface} clsact")
