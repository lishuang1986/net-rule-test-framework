# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Li Shuang
import os
import subprocess
import time
import uuid
from typing import Dict
from ...topo.client_server import ClientServerTopo
from ..base import BaseInfra, LibvirtVMNode


class LibvirtClientServerInfra(ClientServerTopo, BaseInfra):
    """Libvirt VM based client-server infrastructure.

    Currently supports Fedora/RHEL/CentOS based VMs with:
    - Fedora Cloud base image automatically customized via virt-customize
    - Root password set to 'rdma'
    - SSH password authentication enabled
    - rdma-core and related packages installed in base image

    Required pre-step (documented in README):
    1. Download Fedora Cloud image and save as /var/lib/libvirt/images/fedora.qcow2
    """

    # SSH credentials
    ssh_user = 'root'
    ssh_password = 'rdma'

    # VM configuration
    BASE_IMAGE = "/var/lib/libvirt/images/fedora.qcow2"
    VM_NAMES = {"client": "rdma-client", "server": "rdma-server"}
    VM_DISKS = {"client": "/var/lib/libvirt/images/client.img", "server": "/var/lib/libvirt/images/server.img"}
    VM_MEMORY = 2048
    VM_VCPUS = 2

    # Concrete implementation of Client node
    class Client(ClientServerTopo.Client, LibvirtVMNode):
        def __init__(self, executor):
            self._name = "client"
            LibvirtVMNode.__init__(self, executor, self._name, "Client")

        def get_ipv4(self) -> str:
            return self._executor._logical_to_ip[self._name]

        def get_ipv6(self) -> str:
            return self._executor._logical_to_ipv6[self._name]

        def get_iface(self) -> str:
            return self._executor._logical_to_iface[self._name]

    # Concrete implementation of Server node
    class Server(ClientServerTopo.Server, LibvirtVMNode):
        def __init__(self, executor):
            self._name = "server"
            LibvirtVMNode.__init__(self, executor, self._name, "Server")

        def get_ipv4(self) -> str:
            return self._executor._logical_to_ip[self._name]

        def get_ipv6(self) -> str:
            return self._executor._logical_to_ipv6[self._name]

        def get_iface(self) -> str:
            return self._executor._logical_to_iface[self._name]

    def __init__(self):
        self.prefix = str(uuid.uuid4())[:8]
        self._logical_to_ip: Dict[str, str] = {}
        self._logical_to_iface: Dict[str, str] = {}
        self._logical_to_ipv6: Dict[str, str] = {}
        self._created_disks = []
        self._created_vms = []
        self._libvirtd_was_active = False

        # Instantiate node objects, passing self as executor
        self.Client = self.Client(self)
        self.Server = self.Server(self)

    def setup(self) -> Dict[str, str]:
        # 0. Clean up any leftover VMs/disks from previous failed runs
        self._cleanup_leftovers()

        # 1. Check host environment
        self._check_host_environment()

        # 2. Check base image exists
        self._check_base_image()

        # 3. Customize base image (virt-customize) - only once
        self._customize_base_image()

        # 4. Create VM disks from customized base image
        self._create_vm_disks()

        # 5. Define and start VMs
        self._create_vms()

        # 6. Wait for VMs to boot and get IPs + interface names
        self._wait_for_vms_ready()

        # 6.5 Setup temporary IPv6 addresses (lost after reboot)
        self._setup_ipv6()

        # 7. Health check
        self._health_check()

        return self._logical_to_ip.copy()

    def _cleanup_vm(self, vm_name):
        """Clean up a single VM by name"""
        # Check if VM exists
        result = subprocess.run(f"virsh dominfo {vm_name}", shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            return  # VM doesn't exist

        # Stop VM if running
        subprocess.run(f"virsh shutdown {vm_name}", shell=True, stderr=subprocess.DEVNULL)
        for _ in range(30):
            result = subprocess.run(f"virsh domstate {vm_name}", shell=True, capture_output=True, text=True)
            if "shut off" in result.stdout or result.returncode != 0:
                break
            time.sleep(1)
        # Force off if still running
        subprocess.run(f"virsh destroy {vm_name}", shell=True, stderr=subprocess.DEVNULL)
        # Undefine VM
        subprocess.run(f"virsh undefine {vm_name}", shell=True, stderr=subprocess.DEVNULL)

    def _cleanup_leftovers(self):
        """Clean up any leftover VMs and disks from previous failed runs"""
        if BaseInfra.verbose:
            print("[INFO] Cleaning up leftovers from previous runs")

        # Clean up VMs that might exist from previous runs
        for vm_name in self.VM_NAMES.values():
            self._cleanup_vm(vm_name)

        # Clean up disk images
        for disk_path in self.VM_DISKS.values():
            if os.path.exists(disk_path):
                if BaseInfra.verbose:
                    print(f"[INFO] Removing leftover disk: {disk_path}")
                subprocess.run(f"rm -f {disk_path}", shell=True, stderr=subprocess.DEVNULL)

    def cleanup(self):
        # Stop and undefine VMs
        for vm_name in self._created_vms:
            subprocess.run(f"virsh shutdown {vm_name}", shell=True, stderr=subprocess.DEVNULL)
            # Wait for VM to stop
            for _ in range(30):
                result = subprocess.run(f"virsh domstate {vm_name}", shell=True, capture_output=True, text=True)
                if "shut off" in result.stdout:
                    break
                time.sleep(1)
            subprocess.run(f"virsh undefine {vm_name}", shell=True, stderr=subprocess.DEVNULL)

        # Remove disk images (but keep base image and marker)
        for disk in self._created_disks:
            if os.path.exists(disk):
                subprocess.run(f"rm -f {disk}", shell=True, stderr=subprocess.DEVNULL)

        # Restore libvirtd to its original state
        if not self._libvirtd_was_active:
            if BaseInfra.verbose:
                print("[INFO] Stopping libvirtd (restoring original state)")
            subprocess.run("systemctl stop libvirtd", shell=True, stderr=subprocess.DEVNULL)

    def _check_host_environment(self):
        """Check libvirtd is running and default network is active"""
        # Record original libvirtd state
        result = subprocess.run("systemctl is-active libvirtd", shell=True, capture_output=True, text=True)
        self._libvirtd_was_active = result.returncode == 0

        # Start libvirtd if not running
        if not self._libvirtd_was_active:
            if BaseInfra.verbose:
                print("[INFO] libvirtd is not running, starting it now")
            subprocess.run("systemctl start libvirtd", shell=True, check=True)
            # Wait for libvirtd to be ready
            for _ in range(10):
                result = subprocess.run("systemctl is-active libvirtd", shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    break
                time.sleep(1)
            if result.returncode != 0:
                raise RuntimeError("Failed to start libvirtd")

        # Check default network
        result = subprocess.run("virsh net-info default", shell=True, capture_output=True, text=True)
        if result.returncode != 0 or "Active:" not in result.stdout or "yes" not in result.stdout:
            subprocess.run("virsh net-start default", shell=True, check=True)

    def _check_base_image(self):
        """Check base image exists"""
        if not os.path.exists(self.BASE_IMAGE):
            raise RuntimeError(
                f"Base image not found: {self.BASE_IMAGE}\n"
                "Please download Fedora Cloud image and save it as fedora.qcow2\n"
                "See README for download instructions."
            )

    def _customize_base_image(self):
        """Customize base image with virt-customize (only once)"""
        marker_file = f"{self.BASE_IMAGE}.customized"

        # Skip if already customized
        if os.path.exists(marker_file):
            if BaseInfra.verbose:
                print(f"[INFO] Base image already customized, skipping")
            return

        if BaseInfra.verbose:
            print(f"[INFO] Customizing base image: {self.BASE_IMAGE}")

        cmd = (
            f"virt-customize -a {self.BASE_IMAGE} "
            f"--root-password password:{self.ssh_password} "
            f"--run-command 'sed -i \"s/^#PermitRootLogin prohibit-password/PermitRootLogin yes/\" /etc/ssh/sshd_config' "
            f"--run-command 'sed -i \"s/^#PasswordAuthentication yes/PasswordAuthentication yes/\" /etc/ssh/sshd_config' "
            f"--run-command 'systemctl restart sshd' "
            f"--run-command 'dnf install -y rdma-core perftest librdmacm-utils iproute iproute-tc kernel-modules-$(uname -r) libibverbs-utils'"
        )
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to customize base image: {result.stderr}"
            )

        # Create marker file to indicate customization is done
        with open(marker_file, 'w') as f:
            f.write('customized')

        if BaseInfra.verbose:
            print(f"[INFO] Base image customized successfully")

    def _create_vm_disks(self):
        """Create VM disk images from base image"""
        for node, disk_path in self.VM_DISKS.items():
            if os.path.exists(disk_path):
                subprocess.run(f"rm -f {disk_path}", shell=True)
            subprocess.run(f"cp {self.BASE_IMAGE} {disk_path}", shell=True, check=True)
            self._created_disks.append(disk_path)

    def _create_vms(self):
        """Define and start VMs using virt-install"""
        for node, vm_name in self.VM_NAMES.items():
            disk_path = self.VM_DISKS[node]
            cmd = (
                f"virt-install --name {vm_name} "
                f"--memory {self.VM_MEMORY} "
                f"--vcpus {self.VM_VCPUS} "
                f"--disk path={disk_path},format=qcow2 "
                f"--import "
                f"--network network=default,model=virtio "
                f"--graphics vnc "
                f"--noautoconsole "
                f"--osinfo detect=on,require=off"
            )
            subprocess.run(cmd, shell=True, check=True)
            self._created_vms.append(vm_name)

    def _parse_domifaddr(self, vm_name: str):
        """Parse virsh domifaddr output to get IP address.

        Note: The interface name returned is the host-side vnet device name,
        not the interface name inside the VM. Use SSH to get the internal name.
        """
        result = subprocess.run(
            f"virsh domifaddr {vm_name}",
            shell=True, capture_output=True, text=True
        )
        # Output format:
        # Name       MAC address       Protocol     Address
        # -------------------------------------------------------
        # vnet2      52:54:00:xx:xx   ipv4         192.168.122.221/24
        # Note: 'Name' column is host-side vnet device, not VM internal name
        lines = result.stdout.strip().split('\n')
        for line in lines:
            if 'ipv4' in line:
                parts = line.split()
                iface_name = parts[0]
                ip_with_prefix = [p for p in parts if '/' in p][0]
                ip = ip_with_prefix.split('/')[0]
                return iface_name, ip
        return None, None

    def _wait_for_vms_ready(self, timeout: int = 120):
        """Wait for VMs to boot and get IP addresses + interface names"""
        for node, vm_name in self.VM_NAMES.items():
            deadline = time.time() + timeout
            ip = None

            # Wait for IP address via virsh domifaddr
            while time.time() < deadline:
                _, ip = self._parse_domifaddr(vm_name)
                if ip:
                    break
                time.sleep(2)

            if not ip:
                raise RuntimeError(f"Timeout waiting for {vm_name} to get IP address")

            self._logical_to_ip[node] = ip

            # Wait for SSH to be ready
            ssh_ready = False
            last_result = None
            while time.time() < deadline:
                check_cmd = f"sshpass -p '{self.ssh_password}' ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 {self.ssh_user}@{ip} 'echo ok'"
                result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    ssh_ready = True
                    break
                last_result = result
                if BaseInfra.verbose:
                    print(f"[INFO] SSH not ready yet for {vm_name} ({ip}), retrying... stderr: {result.stderr.strip()}")
                time.sleep(2)

            if not ssh_ready:
                error_msg = f"Timeout waiting for SSH to be ready on {vm_name} ({ip})"
                if last_result:
                    error_msg += f"\nLast SSH attempt: returncode={last_result.returncode}, stdout={last_result.stdout}, stderr={last_result.stderr}"
                raise RuntimeError(error_msg)

            # Get interface name inside VM via SSH
            iface_cmd = f"sshpass -p '{self.ssh_password}' ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 {self.ssh_user}@{ip} 'ip -o addr show'"
            iface_result = subprocess.run(iface_cmd, shell=True, capture_output=True, text=True)
            if iface_result.returncode == 0:
                # Parse output to find interface with this IP
                # Format: 1: ens3    inet 192.168.122.221/24 brd ...
                for line in iface_result.stdout.strip().split('\n'):
                    if f" {ip}/" in line or f" {ip} " in line:
                        parts = line.split()
                        iface_name = parts[1].rstrip(':')
                        self._logical_to_iface[node] = iface_name
                        if BaseInfra.verbose:
                            print(f"[INFO] {vm_name} interface inside VM: {iface_name}")
                        break
                if node not in self._logical_to_iface:
                    raise RuntimeError(f"Failed to find interface with IP {ip} inside {vm_name}")
            else:
                raise RuntimeError(f"Failed to get interface name inside {vm_name}")

    def _health_check(self):
        """Basic connectivity check"""
        server_ip = self.Server.get_ipv4()
        self.Client.run(f"ping -c 1 -W 1 {server_ip}")

    def _setup_ipv6(self):
        """Setup temporary IPv6 addresses on VMs (lost after reboot)"""
        ipv6_addrs = {
            "client": "2001:db8:1::2/64",
            "server": "2001:db8:1::1/64"
        }
        for node_name, vm_name in self.VM_NAMES.items():
            node = getattr(self, node_name.capitalize())
            iface = node.get_iface()
            ipv6_with_prefix = ipv6_addrs[node_name]
            if BaseInfra.verbose:
                print(f"[INFO] Adding IPv6 address {ipv6_with_prefix} on {vm_name} (iface={iface})")
            node.run(f"ip -6 addr add {ipv6_with_prefix} dev {iface}")
            # Store IPv6 address without prefix
            self._logical_to_ipv6[node_name] = ipv6_with_prefix.split('/')[0]

    def setup_rdma(self):
        """Setup RDMA (rdma_rxe) on client and server VMs"""
        for node_name in ["client", "server"]:
            node = getattr(self, node_name.capitalize())
            iface = node.get_iface()
            if BaseInfra.verbose:
                print(f"[INFO] Setting up RDMA on {node_name} (iface={iface})")
            # Load rdma_rxe kernel module
            node.run("modprobe rdma_rxe")
            # Add rxe device (ignore error if already exists)
            node.run(f"rdma link add rxe_{node_name} type rxe netdev {iface} 2>/dev/null || true")
            # Show RDMA link status with GID info
            node.run("rdma link show -d")
            # Also show GID table from sysfs
            node.run(f"cat /sys/class/infiniband/rxe_{node_name}/ports/1/gids/2")
