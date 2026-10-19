"""Read-only system status for RudramOS Control Center.

Everything here works without root, so the app can show status without prompting.
Paths are parameters so tests can point them at fake files.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field

VARIANTS = {"none": "pcos", "nvidia": "pcos-nvidia", "nvidia-legacy": "pcos-nvidia-legacy"}


@dataclass
class AdminStatus:
    mode: str
    key_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class DiskStatus:
    encrypted: bool
    tpm_present: bool
    secure_boot: bool | None  # None = unknown


@dataclass
class GraphicsStatus:
    gpu_name: str
    wanted: str
    reason: str
    installed: str


@dataclass
class SystemStatus:
    name: str
    build_date: str
    booted_image: str
    staged_image: str  # "" when no update is waiting for a restart


@dataclass
class AppsStatus:
    approval_on: bool | None  # app approval (fapolicyd) running; None = unknown
    extensions: dict[str, str] = field(default_factory=dict)  # approved browser extension id -> name


PRIVACY_DEFAULTS = {
    "preset": "balanced", "dns": "quad9", "dot": "opportunistic", "trackers": "off",
    "wired_mac": "permanent", "connectivity": "on", "clear_on_exit": "off", "journal_days": "14",
}


@dataclass
class PrivacyStatus:
    settings: dict[str, str]
    killswitch_on: bool


@dataclass
class UsbDevice:
    id: str
    kind: str
    name: str
    level: str  # ok | caution | danger
    message: str


@dataclass
class UsbStatus:
    mode: str  # ask | allow-input | off
    pending: list[UsbDevice] = field(default_factory=list)


@dataclass
class Network:
    uuid: str
    name: str
    device: str
    trusted: bool


# Friendly sharing name -> firewalld service, same as pcos-network
SHARING = {
    "printer-discovery": "mdns",
    "phone": "kdeconnect",
    "remote-desktop": "rdp",
    "file-sharing": "samba",
    "steam-streaming": "steam-streaming",
    "ssh": "ssh",
}


@dataclass
class NetworkStatus:
    networks: list[Network] = field(default_factory=list)
    shared: set[str] = field(default_factory=set)  # friendly names that are on for Home networks


def _read(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default


def admin_status(mode_file: str = "/etc/pcos/admin-mode", mappings_file: str = "/etc/u2f_mappings") -> AdminStatus:
    mode = _read(mode_file, "standard") or "standard"
    counts: dict[str, int] = {}
    for line in _read(mappings_file).splitlines():
        user, sep, keys = line.partition(":")
        if user and sep:
            counts[user] = len([k for k in keys.split(":") if k])
    return AdminStatus(mode=mode, key_counts=counts)


def disk_status(cmdline_file: str = "/proc/cmdline", tpm_dir: str = "/sys/class/tpm", run=subprocess.run) -> DiskStatus:
    cmdline = _read(cmdline_file)
    encrypted = bool(re.search(r"(^|\s)rd\.luks\.(uuid|name)=", cmdline))
    tpm_present = _read(os.path.join(tpm_dir, "tpm0", "tpm_version_major")) == "2"
    secure_boot: bool | None
    try:
        out = run(["mokutil", "--sb-state"], capture_output=True, text=True, timeout=10).stdout
        secure_boot = "SecureBoot enabled" in out if "SecureBoot" in out else None
    except (OSError, subprocess.SubprocessError):
        secure_boot = None
    return DiskStatus(encrypted=encrypted, tpm_present=tpm_present, secure_boot=secure_boot)


def graphics_status(
    detect: str = "/usr/libexec/pcos/pcos-gpu-detect",
    variant_file: str = "/usr/share/pcos/gpu-variant",
    run=subprocess.run,
) -> GraphicsStatus:
    installed = VARIANTS.get(_read(variant_file, "none"), "pcos")
    try:
        out = run([detect], capture_output=True, text=True, timeout=20).stdout.strip()
        wanted, gpu_name, reason = (out.split("\t") + ["", "", ""])[:3]
    except (OSError, subprocess.SubprocessError):
        wanted, gpu_name, reason = installed, "unknown", "detection failed"
    return GraphicsStatus(gpu_name=gpu_name, wanted=wanted or installed, reason=reason, installed=installed)


def apps_status(extensions_file: str = "/etc/pcos/browser-extensions.json", run=subprocess.run) -> AppsStatus:
    approval_on: bool | None
    try:
        state = run(["systemctl", "is-active", "fapolicyd"], capture_output=True, text=True, timeout=10).stdout.strip()
        approval_on = state == "active"
    except (OSError, subprocess.SubprocessError):
        approval_on = None
    extensions: dict[str, str] = {}
    try:
        data = json.loads(_read(extensions_file) or "{}")
        if isinstance(data, dict):
            extensions = {k: (v.get("name") or k) if isinstance(v, dict) else k for k, v in data.items()}
    except ValueError:
        pass
    return AppsStatus(approval_on=approval_on, extensions=extensions)


ESCAPED_COLON = "\\:"  # nmcli -t writes a literal backslash before ":" inside fields
SEP = "\x1f"  # placeholder for escaped colons while splitting


def network_status(trusted_file: str = "/etc/pcos/trusted-networks", run=subprocess.run) -> NetworkStatus:
    trusted = {line.split("\t", 1)[0] for line in _read(trusted_file).splitlines() if line.strip()}
    networks: list[Network] = []
    try:
        out = run(["nmcli", "-t", "-f", "UUID,TYPE,DEVICE,NAME", "connection", "show", "--active"],
                  capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            parts = [p.replace(SEP, ":") for p in line.replace(ESCAPED_COLON, SEP).split(":", 3)]
            if len(parts) < 4 or parts[1] not in ("802-11-wireless", "802-3-ethernet") or not parts[2]:
                continue
            networks.append(Network(uuid=parts[0], name=parts[3], device=parts[2], trusted=parts[0] in trusted))
    except (OSError, subprocess.SubprocessError):
        pass
    shared: set[str] = set()
    try:
        services = run(["firewall-cmd", "--zone=pcos-home", "--list-services"],
                       capture_output=True, text=True, timeout=10).stdout.split()
        shared = {name for name, svc in SHARING.items() if svc in services}
    except (OSError, subprocess.SubprocessError):
        pass
    return NetworkStatus(networks=networks, shared=shared)


def privacy_status(conf: str = "/etc/pcos/privacy.conf", killswitch_rules: str = "/etc/pcos/killswitch.nft") -> PrivacyStatus:
    settings = dict(PRIVACY_DEFAULTS)
    for line in _read(conf).splitlines():
        key, sep, value = line.partition("=")
        if sep and key in settings and not key.startswith("#"):
            settings[key] = value.strip()
    return PrivacyStatus(settings=settings, killswitch_on=os.path.exists(killswitch_rules))


def usb_status(
    mode_file: str = "/etc/pcos/usb-mode",
    pending_dir: str = "/run/pcos/usb-pending",
    describe: str = "/usr/libexec/pcos/pcos-usb-describe",
    run=subprocess.run,
) -> UsbStatus:
    mode = _read(mode_file, "ask") or "ask"
    pending: list[UsbDevice] = []
    try:
        ids = sorted((f for f in os.listdir(pending_dir) if f.isdigit()), key=int)
    except OSError:
        ids = []
    for dev_id in ids:
        rule = _read(os.path.join(pending_dir, dev_id))
        try:
            out = run([describe, rule], capture_output=True, text=True, timeout=10).stdout.strip()
            kind, name, level, message = (out.split("\t") + ["", "", "", ""])[:4]
        except (OSError, subprocess.SubprocessError):
            kind, name, level, message = "USB device", f"Device {dev_id}", "ok", ""
        pending.append(UsbDevice(id=dev_id, kind=kind, name=name, level=level or "ok", message=message))
    return UsbStatus(mode=mode, pending=pending)


def _image_name(ref: str) -> str:
    # "ostree-image-signed:docker://ghcr.io/owner/pcos-nvidia:latest" -> "pcos-nvidia:latest"
    return ref.rsplit("/", 1)[-1] if ref else ""


def system_status(
    os_release: str = "/usr/lib/os-release",
    build_date_file: str = "/usr/share/pcos/build-date",
    run=subprocess.run,
) -> SystemStatus:
    name = "RudramOS"
    for line in _read(os_release).splitlines():
        if line.startswith("PRETTY_NAME="):
            name = line.split("=", 1)[1].strip('"')
    booted = staged = ""
    try:
        out = run(["rpm-ostree", "status", "--json"], capture_output=True, text=True, timeout=30).stdout
        for dep in json.loads(out or "{}").get("deployments", []):
            ref = dep.get("container-image-reference", "")
            if dep.get("booted"):
                booted = _image_name(ref)
            if dep.get("staged"):
                staged = _image_name(ref)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return SystemStatus(name=name, build_date=_read(build_date_file), booted_image=booted, staged_image=staged)
