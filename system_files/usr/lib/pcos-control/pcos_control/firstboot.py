"""First-boot setup ("Welcome to RudramOS"): which steps to show, and whether to start.

No GTK here, so tests can run anywhere. The window is in setup.py; it reuses Control Center's
pages, buttons and admin approval. See docs/DESIGN.md §10.
"""

from __future__ import annotations

import grp
import os
import pwd
import subprocess
from dataclasses import dataclass

SETUP_VERSION = "1"  # bump to show the setup again after adding important steps
SECUREBOOT_KEY = "/etc/pki/akmods/certs/akmods-ublue.der"  # NVIDIA driver signing key (Universal Blue)
MOK_PENDING_FLAG = "/run/pcos-mok-pending"  # set by pcos-gpu-switch when it queued the key


@dataclass
class Context:
    encrypted: bool
    nvidia: bool  # an NVIDIA image variant is installed
    driver_needed: bool  # the graphics card wants a different variant than the installed one
    mok: str  # secure boot key state, see mok_state()
    networks: int  # connected Wi-Fi / wired networks
    phone_link: bool  # GSConnect installed


def mok_state(secure_boot: bool | None, key: str = SECUREBOOT_KEY, pending_flag: str = MOK_PENDING_FLAG,
              run=subprocess.run) -> str:
    """not-needed | enrolled | pending (restart to enroll) | missing (driver can't load)."""
    if not secure_boot or not os.path.exists(key):
        return "not-needed"
    if os.path.exists(pending_flag):
        return "pending"
    try:
        out = run(["mokutil", "--test-key", key], capture_output=True, text=True, timeout=10)
        text = (out.stdout or "") + (out.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return "not-needed"  # can't tell: don't alarm anyone
    if "already enrolled" in text:
        return "enrolled"
    if "enrollment request" in text:
        return "pending"
    if "not enrolled" in text:
        return "missing"
    return "not-needed"


def steps(ctx: Context) -> list[str]:
    """The pages, in order. Pages that have nothing to do on this PC are left out."""
    out = ["welcome", "admin", "disk", "privacy"]
    if ctx.networks:
        out.append("network")
    if ctx.driver_needed or (ctx.nvidia and ctx.mok in ("missing", "pending")):
        out.append("graphics")
    if ctx.phone_link:
        out.append("phone")
    out += ["protect", "done"]
    return out


def marker(config_home: str | None = None) -> str:
    base = config_home or os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "pcos", "setup-done")


def is_done(config_home: str | None = None) -> bool:
    try:
        with open(marker(config_home), encoding="utf-8") as f:
            return f.read().strip() == SETUP_VERSION
    except OSError:
        return False


def mark_done(config_home: str | None = None) -> None:
    path = marker(config_home)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(SETUP_VERSION + "\n")


def is_admin(user: str | None = None, group: str = "wheel") -> bool:
    """The user may approve admin actions (member of wheel)."""
    try:
        pw = pwd.getpwnam(user) if user else pwd.getpwuid(os.getuid())
        gid = grp.getgrnam(group).gr_gid
    except KeyError:
        return False
    return gid in os.getgrouplist(pw.pw_name, pw.pw_gid)


def should_start(config_home: str | None = None, admin: bool | None = None) -> bool:
    """At login: only for admins (others can't change these settings), only until finished."""
    if is_done(config_home):
        return False
    return is_admin() if admin is None else admin


def initial_setup_running(proc: str = "/proc") -> bool:
    """GNOME's own first-login setup is open; ours waits until it's closed."""
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return False
    for pid in pids:
        try:
            with open(os.path.join(proc, pid, "comm"), encoding="utf-8") as f:
                if f.read().strip().startswith("gnome-initial-s"):  # comm is cut at 15 characters
                    return True
        except OSError:
            continue
    return False
