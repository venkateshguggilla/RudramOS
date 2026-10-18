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
