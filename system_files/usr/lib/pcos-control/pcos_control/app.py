"""RudramOS Control Center: one place for the RudramOS security and system settings.

Status is read without root (status.py). Changes go through the existing tools:
steps that need typing or a security-key touch open in a terminal (pcos-terminal-run),
and the graphics driver switch runs through pkexec with its polkit action.
"""

from __future__ import annotations

import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import status  # noqa: E402

APP_ID = "org.pcos.Control"
TERMINAL_RUN = "/usr/libexec/pcos/pcos-terminal-run"
GPU_SWITCH = "/usr/libexec/pcos/pcos-gpu-switch"


def run_in_terminal(title: str, *cmd: str) -> None:
    Gio.Subprocess.new([TERMINAL_RUN, title, *cmd], Gio.SubprocessFlags.NONE)


def info_row(title: str, subtitle: str = "") -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_selectable(True)
    return row


def button_row(title: str, subtitle: str, label: str, callback, suggested: bool = False, sensitive: bool = True) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    if suggested:
        button.add_css_class("suggested-action")
    button.set_sensitive(sensitive)
    button.connect("clicked", lambda *_: callback())
    row.add_suffix(button)
    return row


def group(title: str, description: str, rows: list[Gtk.Widget]) -> Adw.PreferencesGroup:
    g = Adw.PreferencesGroup(title=title, description=description)
    for r in rows:
        g.add(r)
    return g


class Window(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(title="RudramOS Control Center", default_width=780, default_height=660, **kwargs)
        self.stack = Adw.ViewStack()
        self.pages: dict[str, Adw.PreferencesPage] = {}
        self.groups: dict[str, list[Adw.PreferencesGroup]] = {}
        for name, title, icon in (
            ("security", "Security", "security-high-symbolic"),
            ("disk", "Disk", "drive-harddisk-symbolic"),
            ("graphics", "Graphics", "video-display-symbolic"),
            ("system", "System", "computer-symbolic"),
        ):
            page = Adw.PreferencesPage()
            self.pages[name] = page
            self.groups[name] = []
            self.stack.add_titled_with_icon(page, name, title, icon)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh")
        refresh.connect("clicked", lambda *_: self.refresh())
        header.pack_end(refresh)

        self.toasts = Adw.ToastOverlay(child=self.stack)
        toolbar = Adw.ToolbarView(content=self.toasts)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)

        # Refresh when the window comes back into focus, e.g. after a terminal step finishes
        self.connect("notify::is-active", lambda *_: self.refresh() if self.is_active() else None)
        self._loading = False
        self.refresh()

    # ---- data loading (in a thread: rpm-ostree and detection can take a moment) ----

    def refresh(self) -> None:
        if self._loading:
            return
        self._loading = True

        def load():
            data = {
                "admin": status.admin_status(),
                "disk": status.disk_status(),
                "graphics": status.graphics_status(),
                "system": status.system_status(),
            }
            GLib.idle_add(self._apply, data)

        threading.Thread(target=load, daemon=True).start()

    def _set_groups(self, page: str, groups: list[Adw.PreferencesGroup]) -> None:
        for g in self.groups[page]:
            self.pages[page].remove(g)
        for g in groups:
            self.pages[page].add(g)
        self.groups[page] = groups

    def _apply(self, data) -> bool:
        self._set_groups("security", self._security(data["admin"]))
        self._set_groups("disk", self._disk(data["disk"]))
        self._set_groups("graphics", self._graphics(data["graphics"]))
        self._set_groups("system", self._system(data["system"]))
        self._loading = False
        return GLib.SOURCE_REMOVE

    # ---- pages ----

    def _security(self, s: status.AdminStatus) -> list[Adw.PreferencesGroup]:
        me = GLib.get_user_name()
        my_keys = s.key_counts.get(me, 0)
        strong = s.mode == "strong"
        mode_row = info_row(
            "Admin approval",
            "Strong: your password + a touch of your security key" if strong else "Standard: your password (like a Mac)",
        )
        key_rows = [info_row(f"Security keys for {user}", f"{n} registered") for user, n in sorted(s.key_counts.items())]
        if not key_rows:
            key_rows = [info_row("Security keys", "None registered")]
        actions = [
            button_row("Register a security key", "Plug in a FIDO2 key (e.g. YubiKey). Register a backup key too.",
                       "Register", lambda: run_in_terminal("Register security key", "sudo", "pcos-admin-mode", "add-key")),
        ]
        if strong:
            actions.append(button_row("Switch to Standard", "Admin actions will need only your password. Needs your key now.",
                                      "Switch", lambda: run_in_terminal("Switch to Standard mode", "sudo", "pcos-admin-mode", "standard")))
        else:
            actions.append(button_row(
                "Turn on Strong mode",
                "Requires a registered key; runs a password + touch test first." if my_keys else "Register a security key first.",
                "Turn on", lambda: run_in_terminal("Turn on Strong mode", "sudo", "pcos-admin-mode", "strong"),
                suggested=True, sensitive=my_keys > 0))
        if my_keys:
            actions.append(button_row("Test password + key", "Checks that your key works, changes nothing.", "Test",
                                      lambda: run_in_terminal("Test security key", "sudo", "pcos-admin-mode", "test")))
        return [
            group("Admin protection", "How installs and system changes are approved.", [mode_row, *key_rows]),
            group("", "", actions),
        ]

    def _disk(self, s: status.DiskStatus) -> list[Adw.PreferencesGroup]:
        sb = {True: "On", False: "Off: the TPM seal and boot protection need it on", None: "Unknown"}[s.secure_boot]
        info = [
            info_row("Drive encryption", "On (LUKS2)" if s.encrypted else "Off: encryption is chosen when installing (Encrypt my data)"),
            info_row("TPM 2.0 chip", "Present" if s.tpm_present else "Not found: enable TPM / fTPM / PTT in the BIOS"),
            info_row("Secure Boot", sb),
        ]
        groups = [group("Encryption", "Only this PC can read the drive when the key is sealed to its TPM.", info)]
        if s.encrypted:
            def disk(title: str, *args: str):
                return lambda: run_in_terminal(title, "sudo", "pcos-disk-security", *args)

            groups.append(group("Unlock at boot", "Each step opens a terminal and asks for your passphrase.", [
                button_row("Recovery key", "Create a new recovery key. Write it down and keep it away from this PC.",
                           "Create", disk("Create recovery key", "recovery-key"), suggested=True),
                button_row("Unlock automatically", "Use this PC's TPM. Breaks safely if Secure Boot is changed.",
                           "Set up", disk("Unlock with TPM", "tpm"), sensitive=s.tpm_present),
                button_row("TPM + PIN", "Type a short PIN at boot (recommended for laptops).",
                           "Set up", disk("Unlock with TPM + PIN", "tpm-pin"), sensitive=s.tpm_present),
                button_row("Security key", "Unlock with a FIDO2 key (touch + its PIN).",
                           "Set up", disk("Unlock with security key", "fido2")),
                button_row("Re-seal after a BIOS update", "If the drive asked for the recovery key after a firmware update.",
                           "Re-seal", disk("Re-seal TPM", "reseal"), sensitive=s.tpm_present),
                button_row("Show unlock methods", "List what can unlock the drive.",
                           "Show", disk("Disk unlock methods", "status")),
            ]))
        return groups

    def _graphics(self, s: status.GraphicsStatus) -> list[Adw.PreferencesGroup]:
        rows = [
            info_row("Graphics card", s.gpu_name),
            info_row("Installed driver", s.installed),
            info_row("Recommended", f"{s.wanted} ({s.reason})" if s.reason else s.wanted),
        ]
        if s.wanted != s.installed:
            rows.append(button_row("Install the recommended driver", "Downloads in the background, then asks you to restart.",
                                   "Install", lambda: self._switch_driver(s.wanted), suggested=True))
        return [group("Graphics driver", "RudramOS picks the driver from the graphics card it finds.", rows)]

    def _system(self, s: status.SystemStatus) -> list[Adw.PreferencesGroup]:
        rows = [
            info_row("System", s.name),
            info_row("Build date", s.build_date or "unknown"),
            info_row("Running image", s.booted_image or "unknown"),
        ]
        if s.staged_image:
            rows.append(button_row("Update ready", f"{s.staged_image} is installed and starts after a restart.",
                                   "Restart", self._reboot, suggested=True))
        actions = [
            button_row("Check for updates", "Updates also install automatically in the background.",
                       "Check", lambda: run_in_terminal("Check for updates", "sudo", "bootc", "upgrade")),
            button_row("Roll back", "Go back to the previous version at the next restart.",
                       "Roll back", lambda: run_in_terminal("Roll back", "sudo", "bootc", "rollback")),
        ]
        return [group("RudramOS", "", rows), group("Updates", "", actions)]

    # ---- actions ----

    def _toast(self, text: str, button: str | None = None, callback=None) -> None:
        toast = Adw.Toast(title=text, timeout=0 if button else 5)
        if button:
            toast.set_button_label(button)
            toast.connect("button-clicked", lambda *_: callback())
        self.toasts.add_toast(toast)

    def _switch_driver(self, variant: str) -> None:
        self._toast(f"Installing {variant}… this can take several minutes.")
        proc = Gio.Subprocess.new(["pkexec", GPU_SWITCH, variant], Gio.SubprocessFlags.NONE)

        def done(p, result):
            try:
                ok = p.wait_check_finish(result)
            except GLib.Error:
                ok = False
            if ok:
                self._toast("Graphics driver ready. Restart to finish (a blue MOK screen may appear once: password universalblue).",
                            "Restart", self._reboot)
            else:
                self._toast("Driver install didn't finish (cancelled or download failed).")
            self.refresh()

        proc.wait_check_async(None, done)

    def _reboot(self) -> None:
        Gio.Subprocess.new(["systemctl", "reboot"], Gio.SubprocessFlags.NONE)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        win = self.props.active_window or Window(application=self)
        win.present()


def main() -> int:
    return App().run(sys.argv)
