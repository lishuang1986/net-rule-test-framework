#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
set -e

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

echo "==> Installing system dependencies..."

# Detect package manager
if command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
    PKG_INSTALL="$SUDO dnf install -y"
elif command -v apt-get &>/dev/null; then
    PKG_MGR="apt-get"
    PKG_INSTALL="$SUDO apt-get install -y"
else
    echo "Unsupported package manager. Install manually the packages listed in README.md."
    exit 1
fi

# Refresh package index (apt-get only; dnf does this automatically)
if [ "$PKG_MGR" = "apt-get" ]; then
    $SUDO apt-get update
    export DEBIAN_FRONTEND=noninteractive
fi

# pip (may already be present but ensure it's installed)
$PKG_INSTALL python3-pip

# Build toolchain for source compilation
if [ "$PKG_MGR" = "dnf" ]; then
    $PKG_INSTALL gcc make autoconf automake texinfo git
else
    $PKG_INSTALL build-essential autoconf automake texinfo git
fi

# Common test tools
if [ "$PKG_MGR" = "dnf" ]; then
    $PKG_INSTALL \
        iputils \
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
if [ "$PKG_MGR" = "dnf" ]; then
    $PKG_INSTALL \
        libibverbs-utils \
        librdmacm-utils \
        infiniband-diags
fi

echo "==> Installing Python dependencies..."
python3 -m pip install -r requirements.txt

echo "==> Building netperf from source..."
NETPERF_REPO="https://github.com/HewlettPackard/netperf"
BUILD_DIR="/tmp/netperf-build"
if [ ! -d "$BUILD_DIR" ]; then
    git clone --depth 1 "$NETPERF_REPO" "$BUILD_DIR"
fi
cd "$BUILD_DIR"
./autogen.sh
./configure CFLAGS="-std=gnu11 -Wno-implicit-function-declaration"
make
$SUDO make install

echo "==> Setup complete"
