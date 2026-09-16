# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import re


def parse_pingpong_output(host, log_file) -> dict:
    """Parse ibv_pingpong output and extract all metrics.

    Calls ``host.run(f"cat {log_file}")`` once and parses all available
    fields from the output in a single pass.

    Args:
        host: The VM/host object to run commands on
        log_file: Path to the ibv_pingpong output log file

    Returns:
        Dict with the following keys (use ``.get()`` for optional fields):

        - **total_time_sec** (float) — always present, default 0.0
        - **bytes** (int) — total bytes transferred (optional)
        - **mbit_sec** (float) — throughput in Mbit/sec (optional)
        - **iters** (int) — number of iterations (optional)
        - **usec_iter** (float) — latency per iteration in us (optional)
    """
    result = host.run(f"cat {log_file} 2>/dev/null || echo ''")
    output = result.stdout
    data = {}

    # total time: "total time: X seconds" or "total time: X sec"
    match = re.search(r'total time:\s+([\d.]+)\s+(?:seconds|sec)', output)
    if match:
        data['total_time_sec'] = float(match.group(1))
    else:
        # Fallback: any "X seconds" or "X sec" in output
        match = re.search(r'([\d.]+)\s+(?:seconds|sec)', output)
        if match:
            data['total_time_sec'] = float(match.group(1))
        else:
            data['total_time_sec'] = 0.0

    # "102400 bytes in 0.29 seconds = 2.82 Mbit/sec"
    m = re.search(r'(\d+) bytes in ([\d.]+) seconds = ([\d.]+) Mbit/sec', output)
    if m:
        data['bytes'] = int(m.group(1))
        data['mbit_sec'] = float(m.group(3))

    # "1000 iters in 0.29 seconds = 291.72 usec/iter"
    m = re.search(r'(\d+) iters in ([\d.]+) seconds = ([\d.]+) usec/iter', output)
    if m:
        data['iters'] = int(m.group(1))
        data['usec_iter'] = float(m.group(3))

    return data


def parse_ib_write_bw_output(host, log_file) -> dict:
    """Parse ib_write_bw client output and extract bandwidth metrics.

    Calls ``host.run(f"cat {log_file}")`` once and parses the data line
    from the summary table.

    Args:
        host: The VM/host object to run commands on
        log_file: Path to the ib_write_bw client output log file

    Returns:
        Dict with the following keys:

        - **bytes** (int) — message size (optional)
        - **iterations** (int) — number of iterations (optional)
        - **bw_peak_mb_sec** (float) — peak BW in MB/sec (optional)
        - **bw_avg_mb_sec** (float) — average BW in MB/sec (optional)
        - **msg_rate_mpps** (float) — message rate in Mpps (optional)
    """
    result = host.run(f"cat {log_file} 2>/dev/null || echo ''")
    output = result.stdout
    data = {}

    # Data line format (from ib_write_bw summary table):
    #   bytes   #iterations    BW peak[MB/sec]    BW average[MB/sec]   MsgRate[Mpps]
    #   1024    5000           1234.56             1200.00              0.002145
    #
    # Match lines that start with whitespace and a number (byte count),
    # followed by whitespace-separated numeric fields.
    for line in output.split('\n'):
        line_stripped = line.strip()
        m = re.match(r'^(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)', line_stripped)
        if m:
            data['bytes'] = int(m.group(1))
            data['iterations'] = int(m.group(2))
            data['bw_peak_mb_sec'] = float(m.group(3))
            data['bw_avg_mb_sec'] = float(m.group(4))
            data['msg_rate_mpps'] = float(m.group(5))
            # Only take the first matching data line (the summary)
            break

    return data


def parse_iperf3_output(host, log_file) -> dict:
    """Parse iperf3 client output and extract bandwidth metrics.

    Calls ``host.run(f"cat {log_file}")`` once and parses the receiver/sender
    summary lines. Converts Mbits/sec to MB/sec (÷8) to match the convention
    used by other parse functions in this module.

    Args:
        host: The VM/host object to run commands on
        log_file: Path to the iperf3 client output log file

    Returns:
        Dict with keys:

        - **bw_avg_mb_sec** (float) — average bandwidth in MB/sec (receiver)
        - **bw_peak_mb_sec** (float) — peak bandwidth in MB/sec (max of sender & receiver)
    """
    result = host.run(f"cat {log_file} 2>/dev/null || echo ''", check=False)
    output = result.stdout

    data = {
        'bw_avg_mb_sec': 0.0,
        'bw_peak_mb_sec': 0.0,
    }

    # Format with ``iperf3 -f m``:
    #   [  5]   0.00-10.00  sec   112 MBytes  94.0 Mbits/sec  receiver
    for line in output.split('\n'):
        if 'receiver' in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p == 'Mbits/sec' and i > 0:
                    bw_mbits = float(parts[i - 1])
                    data['bw_avg_mb_sec'] = bw_mbits / 8.0
                    data['bw_peak_mb_sec'] = bw_mbits / 8.0
            break

    # Sender line may have a higher value — use as peak
    for line in output.split('\n'):
        if 'sender' in line and 'Mbits/sec' in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p == 'Mbits/sec' and i > 0:
                    data['bw_peak_mb_sec'] = max(
                        data['bw_peak_mb_sec'],
                        float(parts[i - 1]) / 8.0,
                    )
            break

    return data
