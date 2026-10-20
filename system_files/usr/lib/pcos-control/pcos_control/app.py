"""RudramOS Control Center: one place for the RudramOS security and system settings.

Status is read without root (status.py). Changes are buttons that run the RudramOS tools
through pkexec (admin approval with the system's own prompt). Only steps where you type a
secret or touch a security key open a terminal (pcos-terminal-run).
"""

from __future__ import annotations

import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import status  # noqa: E402

APP_ID = "org.pcos.Control"
TERMINAL_RUN = "/usr/libexec/pcos/pcos-terminal-run"
APP_GUARD = "/usr/bin/pcos-app-guard"
BROWSER_EXTENSIONS = "/usr/bin/pcos-browser-extensions"
NETWORK = "/usr/bin/pcos-network"
USB = "/usr/bin/pcos-usb"
PRIVACY = "/usr/bin/pcos-privacy"
KILLSWITCH = "/usr/bin/pcos-killswitch"

DNS_CHOICES = [
    ("quad9", "Quad9 (blocks malware sites)"),
    ("mullvad", "Mullvad (no filtering)"),
    ("cloudflare", "Cloudflare (fast)"),
    ("network", "This network's DNS (less private, for login pages)"),
]
JOURNAL_CHOICES = ["3", "7", "14", "30"]

USB_MODES = {
    "ask": ("Ask for every new device", "Recommended. Keyboards, drives, phones: you approve each one."),
    "allow-input": ("Allow keyboards and mice", "Plain keyboards and mice work right away; everything else asks."),
    "off": ("Off", "Every USB device works without asking (not recommended)."),
}

SHARING_LABELS = {
    "printer-discovery": ("Printer discovery", "Find network printers automatically"),
    "phone": ("Phone link", "Connect your Android phone (GSConnect / KDE Connect)"),
    "remote-desktop": ("Remote desktop", "Let another computer control this one (RDP)"),
    "file-sharing": ("File sharing", "Windows-compatible shared folders (Samba)"),
    "steam-streaming": ("Steam Remote Play", "Stream games to other devices"),
    "ssh": ("Remote login (SSH)", "Also starts the SSH server"),
}
GPU_SWITCH = "/usr/libexec/pcos/pcos-gpu-switch"
UPDATE = "/usr/libexec/pcos/pcos-update"
APP_STORE = "/usr/libexec/pcos/pcos-app-store"
GRUB_THEME = "/usr/libexec/pcos/pcos-grub-theme"
ONLINE_CHECK_EVERY = 600  # seconds between update checks while the window is open


def when(ts: int) -> str:
    return time.strftime("%-d %b %Y, %H:%M", time.localtime(ts)) if ts else "unknown"


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
            ("updates", "Updates", "software-update-available-symbolic"),
            ("security", "Security", "security-high-symbolic"),
            ("apps", "Apps", "application-x-executable-symbolic"),
            ("network", "Network", "network-wireless-symbolic"),
            ("usb", "USB", "drive-removable-media-symbolic"),
            ("privacy", "Privacy", "preferences-system-privacy-symbolic"),
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
        self._updating = False  # an update is downloading
        self._remote_digest = ""  # newest image online, from the last check
        self._checked_at = 0.0  # time.monotonic() of the last check online (0 = never)
        self._checked_clock = ""  # the same, as a time of day for people
        self._last_updates: status.UpdateStatus | None = None
        self._operation: status.Operation | None = None  # driver install / update running now
        self._poll_id = 0
        self._started_here = False  # a driver install started from this window, maybe still at the prompt
        self.refresh()

    def _poll(self) -> bool:
        self.refresh()
        if self._operation or self._started_here:
            return GLib.SOURCE_CONTINUE
        self._poll_id = 0
        return GLib.SOURCE_REMOVE

    def _operation_row(self) -> Adw.ActionRow:
        """Spinner row for a driver install / update that is running (started here or elsewhere)."""
        op = self._operation
        minutes = max(0, int((time.time() - op.started) / 60))
        started = "just now" if minutes == 0 else f"{minutes} min ago"
        title, size = {
            "driver": ("Installing the graphics driver…", "the system with the driver (about 2–3 GB)"),
            "rollback": ("Switching back to the previous version…", "nothing new: the previous version is kept on this PC"),
        }.get(op.kind, ("Downloading the update…", "the update"))
        row = Adw.ActionRow(title=title,
                            subtitle=f"Downloading {size}. Started {started}. You can keep working; "
                                     "a notification appears when it's ready to restart.")
        row.set_subtitle_lines(3)
        row.add_suffix(Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER))
        return row

    # ---- data loading (in a thread: rpm-ostree and detection can take a moment) ----

    def refresh(self, check_online: bool = False) -> None:
        if self._loading:
            return
        self._loading = True
        # Check online when asked, and otherwise at most every 10 minutes
        online = check_online or not self._checked_at or time.monotonic() - self._checked_at > ONLINE_CHECK_EVERY

        def load():
            updates = status.update_status(check_online=online, known_remote=self._remote_digest)
            if online:
                self._remote_digest = updates.remote_digest
                self._checked_at = time.monotonic()
                self._checked_clock = time.strftime("%H:%M")
            data = {
                "updates": updates,
                "operation": status.system_operation(),
                "boot_menu": status.boot_menu_theme_on(),
                "admin": status.admin_status(),
                "apps": status.apps_status(),
                "network": status.network_status(),
                "usb": status.usb_status(),
                "privacy": status.privacy_status(),
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
        self._last_updates = data["updates"]
        self._operation = data["operation"]
        # While a driver install or update runs, refresh every few seconds to show its state
        if self._operation and not self._poll_id:
            self._poll_id = GLib.timeout_add_seconds(5, self._poll)
        self._set_groups("updates", self._updates(data["updates"]))
        self._set_groups("security", self._security(data["admin"]))
        self._set_groups("apps", self._apps(data["apps"]))
        self._set_groups("network", self._network(data["network"]))
        self._set_groups("usb", self._usb(data["usb"]))
        self._set_groups("privacy", self._privacy(data["privacy"]))
        self._set_groups("disk", self._disk(data["disk"]))
        self._set_groups("graphics", self._graphics(data["graphics"], data["updates"]))
        self._set_groups("system", self._system(data["system"], data["boot_menu"]))
        self._loading = False
        return GLib.SOURCE_REMOVE

    # ---- pages ----

    def _updates(self, u: status.UpdateStatus) -> list[Adw.PreferencesGroup]:
        if self._operation and not self._updating:
            state = self._operation_row()
        elif self._updating:
            state = Adw.ActionRow(title="Downloading the update…",
                                  subtitle="You can keep working. This usually takes a few minutes.")
            state.add_suffix(Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER))
        elif u.state == "ready":
            version = f"RudramOS {u.staged.version}" if u.staged and u.staged.version else "The update"
            state = button_row("Update ready", f"{version} is downloaded. Restart to start using it.",
                               "Restart", self._reboot, suggested=True)
        elif u.state == "available":
            state = button_row("Update available",
                               "A newer RudramOS is ready to download. Your files, apps and settings stay as they are.",
                               "Update now", self._update_now, suggested=True)
        elif u.state == "current":
            state = info_row("RudramOS is up to date", f"Checked at {self._checked_clock}." if self._checked_clock else "")
        else:
            state = info_row("Couldn't check for updates",
                             "No internet connection, or the update server can't be reached right now.")
        check = button_row("Check for updates", "", "Check now", lambda: self.refresh(check_online=True),
                           sensitive=not (self._updating or self._operation))

        b = u.booted
        this_pc = [
            info_row("Version", b.version if b and b.version else "unknown"),
            info_row("Installed", when(b.timestamp) if b else "unknown"),
            info_row("Image", b.image if b else "unknown"),
            info_row("Automatic updates",
                     "On: updates download in the background and start after a restart."
                     + (f" Next: {u.next_automatic}." if u.next_automatic else "")),
        ]

        if u.rollback:
            back: list[Gtk.Widget] = [button_row(
                "Go back to the previous version",
                f"{u.rollback.version or u.rollback.image}, installed {when(u.rollback.timestamp)}. "
                "Use this if something stopped working after an update.",
                "Roll back…", lambda r=u.rollback: self._confirm_rollback(r))]
        else:
            back = [info_row("Previous version", "None kept yet. After the next update, the version before it is kept here.")]

        return [
            group("Software update", "", [state, check]),
            group("This PC", "", this_pc),
            group("If something goes wrong", "The previous version is always kept, so going back is safe.", back),
        ]

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

    def _apps(self, s: status.AppsStatus) -> list[Adw.PreferencesGroup]:
        state = {True: "On", False: "Off", None: "Unknown"}[s.approval_on]
        approval = [
            button_row("App Store", "Find and install apps. Installing asks for admin approval.", "Open",
                       lambda: Gio.Subprocess.new([APP_STORE], Gio.SubprocessFlags.NONE), suggested=True),
            info_row("Programs from Downloads, Desktop and USB drives", f"App approval: {state}. They run only after an admin approves them."),
            button_row("Approve a program", "Pick a downloaded program or AppImage you trust.", "Choose…", self._choose_program),
            button_row("Approved programs", "See or remove approvals.", "Show",
                       lambda: run_in_terminal("Approved programs", "sudo", "pcos-app-guard", "list")),
        ]
        if s.approval_on is False:
            approval.append(button_row("Turn app approval on", "Recommended.", "Turn on",
                                       lambda: self._privileged([APP_GUARD, "on"], "App approval is on."), suggested=True))
        elif s.approval_on:
            approval.append(button_row("Turn app approval off", "Downloaded programs would run without approval.", "Turn off",
                                       lambda: self._confirm("Turn app approval off?",
                                                             "Programs from Downloads, the Desktop and USB drives would run without asking.",
                                                             "Turn off", lambda: self._privileged([APP_GUARD, "off"], "App approval is off."),
                                                             destructive=True)))

        entry = Adw.EntryRow(title="addons.mozilla.org link of an extension")
        entry.set_show_apply_button(True)
        entry.connect("apply", lambda e: self._approve_extension(e.get_text().strip()))
        ext_rows: list[Gtk.Widget] = [info_row("uBlock Origin", "Always installed (blocks ads and trackers)")]
        for ext_id, name in sorted(s.extensions.items(), key=lambda kv: kv[1].lower()):
            ext_rows.append(button_row(name, ext_id, "Remove",
                                       lambda i=ext_id: self._privileged([BROWSER_EXTENSIONS, "revoke", i], "Extension removed. Restart Firefox.")))
        ext_rows.append(entry)
        return [
            group("App approval", "Like Gatekeeper on a Mac: you decide what runs.", approval),
            group("Browser extensions", "Firefox can install only the extensions approved here. Paste a link and press Enter.", ext_rows),
        ]

    def _network(self, s: status.NetworkStatus) -> list[Adw.PreferencesGroup]:
        net_rows: list[Gtk.Widget] = []
        for n in s.networks:
            if n.trusted:
                net_rows.append(button_row(n.name, f"Home (trusted) · {n.device}", "Make Public",
                                           lambda u=n.uuid: self._privileged([NETWORK, "trust", u, "public"], "Network is now Public.")))
            else:
                net_rows.append(button_row(n.name, f"Public: nothing can connect to this PC · {n.device}", "Make Home…",
                                           lambda u=n.uuid: self._privileged([NETWORK, "trust", u, "home"], "Network is now Home.")))
        if not net_rows:
            net_rows.append(info_row("No Wi-Fi or wired network connected"))

        share_rows: list[Gtk.Widget] = []
        for name, (title, subtitle) in SHARING_LABELS.items():
            row = Adw.SwitchRow(title=title, subtitle=subtitle, active=name in s.shared)
            row.connect("notify::active", lambda r, _p, nm=name: self._privileged(
                [NETWORK, "share", nm, "on" if r.get_active() else "off"],
                f"{SHARING_LABELS[nm][0]} {'on' if r.get_active() else 'off'} for Home networks."))
            share_rows.append(row)
        if s.shared:
            share_rows.append(button_row("Stop all sharing", "Close everything at once.", "Stop",
                                         lambda: self._privileged([NETWORK, "stop-sharing"], "All sharing stopped.")))
        return [
            group("Networks", "Every network is Public until you mark it Home. On Public networks nothing can connect to this PC.", net_rows),
            group("Sharing on Home networks", "Always closed on Public networks.", share_rows),
        ]

    def _usb(self, s: status.UsbStatus) -> list[Adw.PreferencesGroup]:
        pending_rows: list[Gtk.Widget] = []
        for d in s.pending:
            prefix = "⚠ " if d.level == "danger" else ""
            row = Adw.ActionRow(title=f"{prefix}{d.name}", subtitle=f"{d.kind}. {d.message}")
            row.set_subtitle_lines(3)
            once = Gtk.Button(label="Allow anyway" if d.level == "danger" else "Allow once", valign=Gtk.Align.CENTER)
            once.connect("clicked", lambda *_, i=d.id: self._privileged([USB, "allow", i], "Device allowed until it's unplugged."))
            if d.level == "danger":
                once.add_css_class("destructive-action")
            row.add_suffix(once)
            if d.level != "danger":
                always = Gtk.Button(label="Always allow", valign=Gtk.Align.CENTER)
                always.add_css_class("suggested-action")
                always.connect("clicked", lambda *_, i=d.id: self._privileged([USB, "allow", i, "--permanent"], "Device allowed, now and next time."))
                row.add_suffix(always)
            pending_rows.append(row)
        if not pending_rows:
            pending_rows.append(info_row("No blocked devices", "New USB devices appear here and as a notification."))

        mode_rows: list[Gtk.Widget] = []
        for mode, (title, subtitle) in USB_MODES.items():
            if mode == s.mode:
                mode_rows.append(info_row(f"✓ {title}", subtitle))
            else:
                mode_rows.append(button_row(title, subtitle, "Use", lambda m=mode: self._privileged([USB, "mode", m], f"USB protection: {USB_MODES[m][0]}.")))
        mode_rows += [
            button_row("Connected devices", "Every USB device, in plain words.", "Show",
                       lambda: run_in_terminal("Connected USB devices", "sudo", "pcos-usb", "devices")),
            button_row("Always-allowed devices", "Remove a device with: sudo pcos-usb forget <number>.", "Show",
                       lambda: run_in_terminal("Always-allowed USB devices", "sudo", "pcos-usb", "rules")),
        ]
        return [
            group("Waiting for approval", "Blocked until you allow them. Nothing is asked while the screen is locked.", pending_rows),
            group("USB protection", "Stops unknown USB devices, including fake keyboards (BadUSB).", mode_rows),
        ]

    def _privacy(self, p: status.PrivacyStatus) -> list[Adw.PreferencesGroup]:
        s = p.settings

        def set_option(key: str, value: str) -> None:
            self._privileged([PRIVACY, "set", key, value], "Privacy setting saved.")

        def switch(title: str, subtitle: str, key: str, on_value: str, off_value: str) -> Adw.SwitchRow:
            row = Adw.SwitchRow(title=title, subtitle=subtitle, active=s.get(key) == on_value)
            row.connect("notify::active", lambda r, _p: set_option(key, on_value if r.get_active() else off_value))
            return row

        presets: list[Gtk.Widget] = []
        for name, title, subtitle in (
            ("balanced", "Balanced", "Private without breaking anything. Recommended."),
            ("maximum", "Maximum", "Strict encrypted DNS, ad and tracker blocking, Firefox forgets everything on close."),
        ):
            if s["preset"] == name:
                presets.append(info_row(f"✓ {title}", subtitle))
            else:
                presets.append(button_row(title, subtitle, "Use", lambda n=name: self._privileged([PRIVACY, "preset", n], f"Privacy preset: {n}.")))
        if s["preset"] == "custom":
            presets.insert(0, info_row("✓ Custom", "You changed individual settings below."))

        dns = Adw.ComboRow(title="DNS provider", subtitle="Encrypted (DNS-over-TLS). Your network can't see the sites you look up.",
                           model=Gtk.StringList.new([label for _, label in DNS_CHOICES]))
        keys = [k for k, _ in DNS_CHOICES]
        dns.set_selected(keys.index(s["dns"]) if s["dns"] in keys else 0)
        dns.connect("notify::selected", lambda r, _p: set_option("dns", keys[r.get_selected()]))

        journal = Adw.ComboRow(title="Keep system logs for", model=Gtk.StringList.new([f"{d} days" for d in JOURNAL_CHOICES]))
        journal.set_selected(JOURNAL_CHOICES.index(s["journal_days"]) if s["journal_days"] in JOURNAL_CHOICES else 2)
        journal.connect("notify::selected", lambda r, _p: set_option("journal_days", JOURNAL_CHOICES[r.get_selected()]))

        options = [
            dns,
            switch("Block ads and trackers", "Uses Mullvad's filtering DNS for every app.", "trackers", "on", "off"),
            switch("Strict encrypted DNS", "No DNS at all if encryption isn't possible (some networks block it).", "dot", "strict", "opportunistic"),
            switch("Private address on wired networks", "A different hardware (MAC) address per wired network, like Wi-Fi.", "wired_mac", "stable", "permanent"),
            switch("Detect Wi-Fi login pages", "Checks fedoraproject.org to show hotel/café sign-in pages.", "connectivity", "on", "off"),
            switch("Firefox forgets on close", "Cookies, history and open tabs are cleared when Firefox closes.", "clear_on_exit", "on", "off"),
            journal,
        ]

        recent = Adw.SwitchRow(title="Remember recently used files", subtitle="Just for you; no admin approval needed.")
        try:
            gsettings = Gio.Settings(schema_id="org.gnome.desktop.privacy")
            gsettings.bind("remember-recent-files", recent, "active", Gio.SettingsBindFlags.DEFAULT)
        except (TypeError, GLib.Error):
            recent.set_sensitive(False)

        ks = Adw.SwitchRow(title="VPN kill switch",
                           subtitle="Internet only through your WireGuard VPN. If the VPN drops, traffic stops instead of leaking.",
                           active=p.killswitch_on)
        ks.connect("notify::active", lambda r, _p: self._privileged(
            [KILLSWITCH, "on" if r.get_active() else "off"],
            "VPN kill switch on." if r.get_active() else "VPN kill switch off."))

        return [
            group("Privacy preset", "No telemetry and no usage reports in any preset.", presets),
            group("Settings", "", options),
            group("This account", "", [recent]),
            group("VPN", "Add your WireGuard VPN in Settings → Network → VPN first.", [ks]),
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

    def _graphics(self, s: status.GraphicsStatus, u: status.UpdateStatus) -> list[Adw.PreferencesGroup]:
        rows = [
            info_row("Graphics card", s.gpu_name),
            info_row("Installed driver", s.installed),
            info_row("Recommended", f"{s.wanted} ({s.reason})" if s.reason else s.wanted),
        ]
        # The switch downloads under the new name, or the old pcos name while that's the one available
        staged = u.staged.image.split(":", 1)[0] if u.staged else ""
        downloaded = staged in (s.wanted, "pcos" + s.wanted[len("rudramos"):])
        if self._operation and self._operation.kind == "driver":
            rows.append(self._operation_row())
        elif s.wanted != s.installed and downloaded:
            rows.append(button_row(
                "Driver downloaded: restart to finish",
                "After the restart, if a blue \"MOK Manager\" screen appears: Enroll MOK → Continue → Yes, "
                "type universalblue, then Reboot.",
                "Restart", self._reboot, suggested=True))
        elif s.wanted != s.installed:
            rows.append(button_row("Install the recommended driver", "Downloads in the background, then asks you to restart.",
                                   "Install", lambda: self._switch_driver(s.wanted), suggested=True,
                                   sensitive=self._operation is None))
        return [group("Graphics driver", "RudramOS picks the driver from the graphics card it finds.", rows)]

    def _system(self, s: status.SystemStatus, boot_menu_on: bool) -> list[Adw.PreferencesGroup]:
        rows = [
            info_row("System", s.name),
            info_row("Build date", s.build_date or "unknown"),
            info_row("Running image", s.booted_image or "unknown"),
        ]
        boot_menu = Adw.SwitchRow(
            title="RudramOS boot menu",
            subtitle="The trishul art in the boot menu (shown after a failed start, or while holding Shift). Off: the plain menu.",
            active=boot_menu_on)
        boot_menu.connect("notify::active", lambda r, _p: self._privileged(
            [GRUB_THEME, "on" if r.get_active() else "off"],
            "Boot menu: RudramOS theme." if r.get_active() else "Boot menu: plain."))
        start_up = [
            boot_menu,
            button_row("Restart into BIOS / UEFI settings",
                       "For Secure Boot, TPM and start-up order. Save your work first.",
                       "Restart…", self._confirm_firmware_restart),
        ]
        return [group("RudramOS", "Updates are on the Updates page.", rows), group("Start-up", "", start_up)]

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
        # Keep refreshing (also while the approval prompt is open) so the progress row appears
        self._started_here = True
        if not self._poll_id:
            self._poll_id = GLib.timeout_add_seconds(3, self._poll)

        def done(p, result):
            self._started_here = False
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

    def _privileged(self, argv: list[str], ok_text: str, ok_button: str | None = None, ok_callback=None,
                    finished=None, check_online: bool = False) -> None:
        """Runs a RudramOS tool through pkexec (admin approval), then refreshes.

        finished(ok) runs before the refresh, whatever the outcome.
        """
        proc = Gio.Subprocess.new(["pkexec", *argv], Gio.SubprocessFlags.STDERR_PIPE)

        def done(p, result):
            try:
                _, _, err = p.communicate_utf8_finish(result)
                ok = p.get_successful()
            except GLib.Error as e:
                ok, err = False, e.message
            if finished:
                finished(ok)
            if ok:
                self._toast(ok_text, ok_button, ok_callback)
            elif p.get_exit_status() not in (126, 127):  # 126/127: approval cancelled
                self._toast((err or "Something went wrong.").strip().splitlines()[-1])
            self.refresh(check_online=check_online)

        proc.communicate_utf8_async(None, None, done)

    def _update_now(self) -> None:
        self._updating = True
        if self._last_updates:  # show the spinner at once
            self._set_groups("updates", self._updates(self._last_updates))

        def finished(ok: bool) -> None:
            self._updating = False

        self._privileged([UPDATE, "upgrade"], "Update downloaded. Restart to start using it.",
                         "Restart", self._reboot, finished=finished, check_online=True)

    def _confirm(self, heading: str, body: str, action: str, callback, destructive: bool = False) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("go", action)
        dialog.set_response_appearance("go", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.connect("response", lambda _d, r: callback() if r == "go" else None)
        dialog.present(self)

    def _confirm_rollback(self, previous: status.Deployment) -> None:
        self._confirm(
            "Go back to the previous version?",
            f"RudramOS {previous.version or previous.image} will start after the next restart. "
            "The current version isn't deleted: the next update brings you forward again.",
            "Roll back",
            lambda: self._privileged([UPDATE, "rollback"], "Done. Restart to use the previous version.",
                                     "Restart", self._reboot),
            destructive=True)

    def _confirm_firmware_restart(self) -> None:
        def restart():
            proc = Gio.Subprocess.new(["systemctl", "reboot", "--firmware-setup"], Gio.SubprocessFlags.STDERR_PIPE)

            def done(p, result):
                try:
                    p.communicate_utf8_finish(result)
                except GLib.Error:
                    pass
                if not p.get_successful():
                    self._toast("This PC can't restart straight into its settings. Restart and press F2, Del or Esc while it starts.")

            proc.communicate_utf8_async(None, None, done)

        self._confirm("Restart into BIOS / UEFI settings?",
                      "The PC restarts now and opens its firmware settings. Unsaved work will be lost.",
                      "Restart", restart)

    def _approve_extension(self, link: str) -> None:
        if link:
            self._privileged([BROWSER_EXTENSIONS, "approve", link], "Extension approved. Restart Firefox to install it.")

    def _choose_program(self) -> None:
        dialog = Gtk.FileDialog(title="Choose a program to approve")
        downloads = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if downloads:
            dialog.set_initial_folder(Gio.File.new_for_path(downloads))

        def picked(d, result):
            try:
                f = d.open_finish(result)
            except GLib.Error:
                return  # cancelled
            if f and f.get_path():
                self._privileged([APP_GUARD, "approve", f.get_path()], f"Approved {f.get_basename()}. Open it again.")

        dialog.open(self, None, picked)

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
