# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
"""nftables DROP rule tests.

Verify that a DROP rule for ICMP/ICMPv6 blocks traffic when applied on the
server input/output hooks and on the router forward/prerouting/postrouting
hooks. Tests invoke the nft binary explicitly so nf_tables is exercised
instead of the legacy ip_tables/ip6_tables modules.

The nft elements exercised by these tests, mapped to the source they relate
to (kernel paths relative to ``net/netfilter/``, user-space paths relative
to the nftables tree):

    * ``meta l4proto`` (implicit L4 dependency)  -> ``nft_meta.c`` /
      ``src/expr/meta.c``
    * ``payload`` load of the ICMP type byte     -> ``nft_payload.c`` /
      ``src/expr/payload.c``
    * ``cmp eq`` (relational compare)            -> ``nft_cmp.c`` /
      ``src/expr/cmp.c``
    * ``immediate ... drop`` (verdict)           -> ``nft_immediate.c`` /
      ``src/expr/immediate.c``
    * ``type filter hook ...`` base chain        -> ``nft_chain_filter.c``
      (registered through ``nf_tables_api.c``)

``icmp`` / ``icmpv6`` are not standalone kernel expressions: user space
(``src/proto.c`` and ``src/expr/payload.c``) expands ``icmp type <value>``
into a ``meta l4proto`` dependency, a ``payload`` load at transport header
offset 0 and a ``cmp`` against the numeric type.
"""

import pytest
from framework.helpers import is_100_percent_loss


@pytest.mark.netfilter
def test_target_drop_icmp_client_server(client_server_env):
    """Verify nftables DROP on the server input/output chains blocks ICMP.

    Adds input and output DROP rules for ICMP on the server, confirms the
    client's ping loses 100% of packets, then removes the rules.

    The INPUT rule ``nft add rule ip filter input icmp type echo-request
    drop`` compiles to::

        [ meta load l4proto => reg 1 ]                        # nft_meta.c
        [ cmp eq reg 1 0x00000001 ]                           # nft_cmp.c (ICMP)
        [ payload load 1b @ transport header + 0 => reg 1 ]   # nft_payload.c
        [ cmp eq reg 1 0x00000008 ]                           # nft_cmp.c (echo-request)
        [ immediate reg 0 drop ]                              # nft_immediate.c

    The OUTPUT rule (``icmp type echo-reply drop``) yields the same sequence
    with the final ``cmp`` against ``0x00000000`` (echo-reply).
    """
    infra = client_server_env
    server_ipv4 = infra.Server.get_ipv4()

    infra.Server.run("nft add table ip filter")
    infra.Server.run(
        "nft add chain ip filter input "
        "{ type filter hook input priority 0 \\; }"
    )
    infra.Server.run(
        "nft add chain ip filter output "
        "{ type filter hook output priority 0 \\; }"
    )

    try:
        # INPUT test
        infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}")

        infra.Server.run("nft add rule ip filter input icmp type echo-request drop")
        result = infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Server.run(
            "nft flush chain ip filter input"
        )

        # OUTPUT test
        infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}")

        infra.Server.run("nft add rule ip filter output icmp type echo-reply drop")
        result = infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Server.run(
            "nft flush chain ip filter output"
        )
    finally:
        infra.Server.run("nft delete table ip filter", check=False)


@pytest.mark.netfilter
def test_target_drop_icmp_router(router_env):
    """Verify nftables DROP on the router forward/prerouting/postrouting hooks.

    Adds DROP rules for ICMP on the router's forward, prerouting and
    postrouting chains in turn, confirms the client's ping to the server
    loses 100% of packets each time, then removes the rule.

    Each rule (``... icmp type echo-request drop``) compiles to::

        [ meta load l4proto => reg 1 ]                        # nft_meta.c
        [ cmp eq reg 1 0x00000001 ]                           # nft_cmp.c (ICMP)
        [ payload load 1b @ transport header + 0 => reg 1 ]   # nft_payload.c
        [ cmp eq reg 1 0x00000008 ]                           # nft_cmp.c (echo-request)
        [ immediate reg 0 drop ]                              # nft_immediate.c

    The ``forward``/``prerouting``/``postrouting`` base chains are attached
    to their hooks by ``nft_chain_filter.c`` through the nf_tables netlink
    API (``nf_tables_api.c``); ``priority mangle`` is the numeric -150.
    """
    infra = router_env
    server_ipv4 = infra.Server.get_ipv4()

    infra.Router.run("nft add table ip filter")
    infra.Router.run(
        "nft add chain ip filter forward "
        "{ type filter hook forward priority 0 \\; }"
    )
    infra.Router.run(
        "nft add chain ip filter prerouting "
        "{ type filter hook prerouting priority mangle \\; }"
    )
    infra.Router.run(
        "nft add chain ip filter postrouting "
        "{ type filter hook postrouting priority mangle \\; }"
    )

    try:
        # FORWARD test
        infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}")

        infra.Router.run("nft add rule ip filter forward icmp type echo-request drop")
        result = infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Router.run("nft flush chain ip filter forward")

        # PREROUTING test
        infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}")

        infra.Router.run(
            "nft add rule ip filter prerouting icmp type echo-request drop"
        )
        result = infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Router.run("nft flush chain ip filter prerouting")

        # POSTROUTING test
        infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}")

        infra.Router.run(
            "nft add rule ip filter postrouting icmp type echo-request drop"
        )
        result = infra.Client.run(f"ping -c 1 -W 1 {server_ipv4}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Router.run("nft flush chain ip filter postrouting")
    finally:
        infra.Router.run("nft delete table ip filter", check=False)


@pytest.mark.netfilter
def test_target_drop_icmpv6_client_server(client_server_env):
    """Verify nftables DROP on the server input/output chains blocks ICMPv6.

    Adds input and output DROP rules for ICMPv6 on the server, confirms the
    client's IPv6 ping loses 100% of packets, then removes the rules.

    The INPUT rule ``nft add rule ip6 filter input icmpv6 type echo-request
    drop`` compiles to::

        [ meta load l4proto => reg 1 ]                        # nft_meta.c
        [ cmp eq reg 1 0x0000003a ]                           # nft_cmp.c (ICMPv6, 58)
        [ payload load 1b @ transport header + 0 => reg 1 ]   # nft_payload.c
        [ cmp eq reg 1 0x00000080 ]                           # nft_cmp.c (echo-request, 128)
        [ immediate reg 0 drop ]                              # nft_immediate.c

    The OUTPUT rule (``icmpv6 type echo-reply drop``) compares the type byte
    against ``0x00000081`` (echo-reply, 129) instead.
    """
    infra = client_server_env
    server_ipv6 = infra.Server.get_ipv6()

    infra.Server.run("nft add table ip6 filter")
    infra.Server.run(
        "nft add chain ip6 filter input "
        "{ type filter hook input priority 0 \\; }"
    )
    infra.Server.run(
        "nft add chain ip6 filter output "
        "{ type filter hook output priority 0 \\; }"
    )

    try:
        # INPUT test
        infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}")

        infra.Server.run(
            "nft add rule ip6 filter input icmpv6 type echo-request drop"
        )
        result = infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Server.run("nft flush chain ip6 filter input")

        # OUTPUT test
        infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}")

        infra.Server.run(
            "nft add rule ip6 filter output icmpv6 type echo-reply drop"
        )
        result = infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Server.run("nft flush chain ip6 filter output")
    finally:
        infra.Server.run("nft delete table ip6 filter", check=False)


@pytest.mark.netfilter
def test_target_drop_icmpv6_router(router_env):
    """Verify nftables DROP on the router forward/prerouting/postrouting hooks.

    Adds DROP rules for ICMPv6 on the router's forward, prerouting and
    postrouting chains in turn, confirms the client's IPv6 ping to the server
    loses 100% of packets each time, then removes the rule.

    Each rule (``... icmpv6 type echo-request drop``) compiles to::

        [ meta load l4proto => reg 1 ]                        # nft_meta.c
        [ cmp eq reg 1 0x0000003a ]                           # nft_cmp.c (ICMPv6, 58)
        [ payload load 1b @ transport header + 0 => reg 1 ]   # nft_payload.c
        [ cmp eq reg 1 0x00000080 ]                           # nft_cmp.c (echo-request, 128)
        [ immediate reg 0 drop ]                              # nft_immediate.c

    The ``forward``/``prerouting``/``postrouting`` base chains are attached
    to their hooks by ``nft_chain_filter.c`` through the nf_tables netlink
    API (``nf_tables_api.c``); ``priority mangle`` is the numeric -150.
    """
    infra = router_env
    server_ipv6 = infra.Server.get_ipv6()

    infra.Router.run("nft add table ip6 filter")
    infra.Router.run(
        "nft add chain ip6 filter forward "
        "{ type filter hook forward priority 0 \\; }"
    )
    infra.Router.run(
        "nft add chain ip6 filter prerouting "
        "{ type filter hook prerouting priority mangle \\; }"
    )
    infra.Router.run(
        "nft add chain ip6 filter postrouting "
        "{ type filter hook postrouting priority mangle \\; }"
    )

    try:
        # FORWARD test
        infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}")

        infra.Router.run(
            "nft add rule ip6 filter forward icmpv6 type echo-request drop"
        )
        result = infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Router.run("nft flush chain ip6 filter forward")

        # PREROUTING test
        infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}")

        infra.Router.run(
            "nft add rule ip6 filter prerouting icmpv6 type echo-request drop"
        )
        result = infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Router.run("nft flush chain ip6 filter prerouting")

        # POSTROUTING test
        infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}")

        infra.Router.run(
            "nft add rule ip6 filter postrouting icmpv6 type echo-request drop"
        )
        result = infra.Client.run(f"ping -6 -c 1 -W 1 {server_ipv6}", expect="failed")

        assert is_100_percent_loss(result.stdout + result.stderr)
        infra.Router.run("nft flush chain ip6 filter postrouting")
    finally:
        infra.Router.run("nft delete table ip6 filter", check=False)
