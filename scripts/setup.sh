#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
set -e

echo "==> Installing system dependencies..."

# Detect package manager
if command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
    PKG_INSTALL="sudo dnf install -y"
elif command -v apt-get &>/dev/null; then
    PKG_MGR="apt-get"
    PKG_INSTALL="sudo apt-get install -y"
else
    echo "Unsupported package manager. Install manually the packages listed in README.md."
    exit 1
fi

# Refresh package index (apt-get only; dnf does this automatically)
if [ "$PKG_MGR" = "apt-get" ]; then
    sudo apt-get update
fi

# pip (may already be present but ensure it's installed)
$PKG_INSTALL python3-pip

# Common test tools
if [ "$PKG_MGR" = "dnf" ]; then
    $PKG_INSTALL \
        iproute-tc \
        iptables \
        nftables \
        tcpdump \
        wireshark
elif [ "$PKG_MGR" = "apt-get" ]; then
    $PKG_INSTALL \
        iputils-ping \
        iproute2 \
        iptables \
        nftables \
        tcpdump \
        tshark
fi

# Firewall test dependencies (cgroupv2 meta matching)
if [ "$PKG_MGR" = "dnf" ]; then
    $PKG_INSTALL libcgroup-tools
else
    $PKG_INSTALL cgroup-tools
fi

# RoCEv2 / RDMA host utilities (diagnostics, debugging)
$PKG_INSTALL \
    libibverbs-utils \
    librdmacm-utils \
    infiniband-diags

echo "==> Installing Python dependencies..."
pip install -r requirements.txt

echo "==> Setup complete"
