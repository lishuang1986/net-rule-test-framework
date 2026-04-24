# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import re


def is_100_percent_loss(output: str) -> bool:
    """Check if output indicates 100% packet loss or network unreachable"""
    return ("100% packet loss" in output or 
            "Network is unreachable" in output)


def get_avg_rtt(output: str) -> float:
    """Extract average RTT from ping output"""
    match = re.search(r"= \d+\.\d+/(\d+\.\d+)/\d+\.\d+", output)
    if match:
        return float(match.group(1))
    return -1
