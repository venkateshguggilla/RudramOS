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

VARIANTS = {"none": "rudramos", "nvidia": "rudramos-nvidia", "nvidia-legacy": "rudramos-nvidia-legacy"}


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
    installed = VARIANTS.get(_read(variant_file, "none"), "rudramos")
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


@dataclass
class Deployment:
    image: str  # "rudramos:latest"
    ref: str  # "ghcr.io/owner/rudramos:latest" (what updates come from)
    digest: str  # "sha256:..."
    version: str  # "44.20261020.0"
    timestamp: int  # seconds since 1970, 0 = unknown


@dataclass
class UpdateStatus:
    booted: Deployment | None
    staged: Deployment | None  # downloaded, starts at the next restart
    rollback: Deployment | None  # the previous version, kept for going back
    remote_digest: str  # newest image online; "" = couldn't check
    state: str  # ready | available | current | unknown
    next_automatic: str  # when the automatic update runs next, "" if unknown


def _deployment(dep: dict) -> Deployment:
    ref = dep.get("container-image-reference", "")
    return Deployment(
        image=_image_name(ref),
        ref=ref.split("docker://", 1)[-1] if "docker://" in ref else "",
        digest=dep.get("container-image-reference-digest", "") or "",
        version=str(dep.get("version", "") or ""),
        timestamp=int(dep.get("timestamp", 0) or 0),
    )


def update_status(check_online: bool = True, known_remote: str = "", run=subprocess.run) -> UpdateStatus:
    """Installed, downloaded and previous versions, and whether a newer image is online.

    No root needed: rpm-ostree status is readable by everyone, and the check online only
    reads the image's manifest digest (skopeo), it downloads nothing. Without check_online,
    known_remote (the digest from an earlier check) is used instead.
    """
    booted = staged = rollback = None
    try:
        out = run(["rpm-ostree", "status", "--json"], capture_output=True, text=True, timeout=30).stdout
        for dep in json.loads(out or "{}").get("deployments", []):
            d = _deployment(dep)
            if dep.get("booted"):
                booted = d
            elif dep.get("staged"):
                staged = d
            elif rollback is None:
                rollback = d
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    remote = known_remote
    if check_online and booted and booted.ref:
        remote = ""
        target = staged.ref if staged and staged.ref else booted.ref
        try:
            res = run(["skopeo", "inspect", "--no-tags", "--retry-times", "2", "--format", "{{.Digest}}", f"docker://{target}"],
                      capture_output=True, text=True, timeout=90)
            if getattr(res, "returncode", 0) == 0 and res.stdout.strip().startswith("sha256:"):
                remote = res.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass

    if staged and (not remote or staged.digest == remote):
        state = "ready"
    elif not remote or not booted:
        state = "unknown"
    elif booted.digest == remote:
        state = "current"
    else:
        state = "available"

    next_automatic = ""
    for timer in ("uupd.timer", "bootc-fetch-apply-updates.timer"):
        try:
            value = run(["systemctl", "show", timer, "-p", "NextElapseUSecRealtime", "--value"],
                        capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if value and value != "n/a":
            next_automatic = value
            break
    return UpdateStatus(booted=booted, staged=staged, rollback=rollback, remote_digest=remote,
                        state=state, next_automatic=next_automatic)


@dataclass
class Operation:
    kind: str  # driver | update | rollback
    started: float  # seconds since 1970


def system_operation(proc: str = "/proc") -> Operation | None:
    """A driver install, update or rollback that is running right now (from any app or a terminal).

    Found from the process list, so it's seen even after the Control Center was closed and opened
    again. Readable without root.
    """
    try:
        btime = next(int(line.split()[1]) for line in _read(os.path.join(proc, "stat")).splitlines()
                     if line.startswith("btime "))
        ticks = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        entries = os.listdir(proc)
    except (StopIteration, ValueError, OSError):
        return None
    found: list[tuple[int, Operation]] = []  # (priority, operation)
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc, entry, "cmdline"), "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
            stat = _read(os.path.join(proc, entry, "stat"))
            start = btime + int(stat[stat.rindex(")") + 2:].split()[19]) / ticks
        except (OSError, ValueError, IndexError):
            continue
        names = [os.path.basename(a) for a in argv[:3]]
        if "pcos-gpu-switch" in names:
            found.append((0, Operation("driver", start)))
        elif "pcos-update" in names:
            found.append((1, Operation("rollback" if "rollback" in argv else "update", start)))
        elif argv and os.path.basename(argv[0]) == "bootc" and len(argv) > 1 and argv[1] in ("switch", "upgrade"):
            found.append((2, Operation("driver" if argv[1] == "switch" else "update", start)))
    return min(found, key=lambda f: (f[0], f[1].started))[1] if found else None


def boot_menu_theme_on(flag: str = "/etc/pcos/no-grub-theme") -> bool:
    return not os.path.exists(flag)


def _image_name(ref: str) -> str:
    # "ostree-image-signed:docker://ghcr.io/owner/rudramos-nvidia:latest" -> "rudramos-nvidia:latest"
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
