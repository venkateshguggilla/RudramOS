"""RudramOS Control Center: one place for the RudramOS security and system settings.

Status is read without root (status.py). Changes are buttons that run the RudramOS tools
through pkexec (admin approval with the system's own prompt). Steps where you type a passphrase
or PIN, or touch a security key, happen in dialogs (dialogs.py) that send secrets on stdin.
"""

from __future__ import annotations

import re
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import dialogs, status  # noqa: E402

APP_ID = "org.pcos.Control"
CONTROL_CENTER = "/usr/bin/pcos-control"
SETUP = "/usr/bin/pcos-setup"
APP_GUARD = "/usr/bin/pcos-app-guard"
BROWSER_EXTENSIONS = "/usr/bin/pcos-browser-extensions"
NETWORK = "/usr/bin/pcos-network"
USB = "/usr/bin/pcos-usb"
PRIVACY = "/usr/bin/pcos-privacy"
KILLSWITCH = "/usr/bin/pcos-killswitch"
ADMIN_MODE = "/usr/bin/pcos-admin-mode"
DISK = "/usr/bin/pcos-disk-security"

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
PHONE = "/usr/bin/pcos-phone"

# GSConnect plugins a paired phone can use, in the order shown on the Phone page
PHONE_PERMISSIONS = [
    ("notification", "Notifications", "See the phone's notifications here and reply to them"),
    ("sms", "Text messages", "Read and send SMS from this PC"),
    ("telephony", "Calls", "Incoming call alerts; music pauses during a call"),
    ("share", "Files and links", "Send files and links both ways"),
    ("clipboard", "Shared clipboard", "Copy on one, paste on the other"),
    ("sftp", "Browse phone files", "Open the phone's storage in Files"),
    ("battery", "Battery", "Show the phone's battery level"),
    ("findmyphone", "Find my phone", "Make the phone ring from this PC"),
    ("mpris", "Media controls", "Control music and videos on this PC from the phone"),
    ("mousepad", "Control this PC", "The phone can move the mouse and type here"),
    ("runcommand", "Run commands on this PC", "The phone can start commands set up in GSConnect"),
]
ONLINE_CHECK_EVERY = 600  # seconds between update checks while the window is open


def when(ts: int) -> str:
    return time.strftime("%-d %b %Y, %H:%M", time.localtime(ts)) if ts else "unknown"


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
        super().__init__(title="RudramOS Control Center", default_width=1000, default_height=700, **kwargs)
        self.stack = Adw.ViewStack()
        self.pages: dict[str, Adw.PreferencesPage] = {}
        self.groups: dict[str, list[Adw.PreferencesGroup]] = {}
        # Pages in a sidebar, like GNOME Settings (ten names don't fit as tabs)
        sidebar = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        sidebar.add_css_class("navigation-sidebar")
        order: list[str] = []
        titles: dict[str, str] = {}
        for name, title, icon in (
            ("updates", "Updates", "software-update-available-symbolic"),
            ("security", "Security", "security-high-symbolic"),
            ("apps", "Apps", "application-x-executable-symbolic"),
            ("phone", "Phone", "phone-symbolic"),
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
            order.append(name)
            titles[name] = title
            item = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            item.append(Gtk.Image(icon_name=icon))
            item.append(Gtk.Label(label=title, xalign=0))
            sidebar.append(Gtk.ListBoxRow(child=item))

        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_title_widget(Adw.WindowTitle(title="Control Center"))
        sidebar_view = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=sidebar, hscrollbar_policy=Gtk.PolicyType.NEVER))
        sidebar_view.add_top_bar(sidebar_header)

        header = Adw.HeaderBar()
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh")
        refresh.connect("clicked", lambda *_: self.refresh())
        header.pack_end(refresh)
        self.toasts = Adw.ToastOverlay(child=self.stack)
        content_view = Adw.ToolbarView(content=self.toasts)
        content_view.add_top_bar(header)
        content = Adw.NavigationPage(title=titles[order[0]], child=content_view)

        split = Adw.NavigationSplitView(sidebar=Adw.NavigationPage(title="Control Center", child=sidebar_view),
                                        content=content, min_sidebar_width=200, max_sidebar_width=240)
        self.set_content(split)

        def page_chosen(_list, row):
            if row is not None and self.stack.get_visible_child_name() != order[row.get_index()]:
                self.stack.set_visible_child_name(order[row.get_index()])

        def page_shown(*_):
            name = self.stack.get_visible_child_name()
            content.set_title(titles.get(name, ""))
            row = sidebar.get_row_at_index(order.index(name)) if name in order else None
            if row is not None and sidebar.get_selected_row() is not row:
                sidebar.select_row(row)

        sidebar.connect("row-selected", page_chosen)
        self.stack.connect("notify::visible-child-name", page_shown)
        page_shown()

        # Refresh when the window comes back into focus, e.g. after a dialog or another app changed something
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
        self._open_phones: set[str] = set()  # paired phones whose permissions are shown
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
                "phone": status.phone_status(),
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
        self._set_groups("phone", self._phone(data["phone"], data["network"]))
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
                       "Register", lambda: dialogs.run(
                           self, "Register a security key", [ADMIN_MODE, "add-key"],
                           hint="Plug in the key. After the password window, touch it when it blinks.",
                           on_done=lambda ok, _o: self.refresh())),
        ]
        if strong:
            actions.append(button_row("Switch to Standard", "Admin actions will need only your password. Needs your key now.",
                                      "Switch", lambda: dialogs.run(self, "Switch to Standard mode", [ADMIN_MODE, "standard"],
                                                                    on_done=lambda ok, _o: self.refresh())))
        else:
            actions.append(button_row(
                "Turn on Strong mode",
                "Requires a registered key; runs a password + touch test first." if my_keys else "Register a security key first.",
                "Turn on", lambda: self._key_test("Turn on Strong mode", "strong",
                                                  "First a test: your password, then a touch of your key. Strong mode "
                                                  "turns on only if the test passes, so you can't lock yourself out."),
                suggested=True, sensitive=my_keys > 0))
        if my_keys:
            actions.append(button_row("Test password + key", "Checks that your key works, changes nothing.", "Test",
                                      lambda: self._key_test("Test password + key", "test",
                                                             "Type your password, then touch your key when it blinks.")))
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
                       lambda: dialogs.show_list(self, "Approved programs",
                                                 "These run from Downloads, the Desktop or USB drives. Remove one to block it again.",
                                                 [APP_GUARD, "list"], dialogs.parse_approved_programs,
                                                 "No programs approved yet.")),
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

    def _phone(self, s: status.PhoneStatus, net: status.NetworkStatus) -> list[Adw.PreferencesGroup]:
        groups = []
        link: list[Gtk.Widget] = []
        if not s.installed:
            link.append(info_row("Phone link isn't installed", "GSConnect is missing from this version of RudramOS."))
        else:
            on = Adw.SwitchRow(title="Phone link", subtitle="Notifications, texts, calls, files and clipboard",
                               active=bool(s.enabled))
            on.connect("notify::active", lambda r, _p: self._user_cmd(
                ["gnome-extensions", "enable" if r.get_active() else "disable", status.GSCONNECT],
                "Phone link is on." if r.get_active() else "Phone link is off."))
            link.append(on)
            if "phone" not in net.shared:
                link.append(button_row("Allow phones on Home networks",
                                       "Phones can't reach this PC yet. They will only ever be allowed on networks you mark Home.",
                                       "Allow…", lambda: self._privileged([NETWORK, "share", "phone", "on"],
                                                                          "Phones can connect on Home networks."),
                                       suggested=True))
            elif not any(n.trusted for n in net.networks):
                link.append(info_row("This network is Public",
                                     "Phones can't connect here. Mark your home Wi-Fi as Home on the Network page."))
            link.append(button_row("Pair a phone",
                                   "Install KDE Connect on the phone (Play Store or F-Droid), open it on the same Wi-Fi, "
                                   "then pair here. Both sides must accept.",
                                   "Pair…", lambda: self._user_cmd(["gnome-extensions", "prefs", status.GSCONNECT], ""),
                                   sensitive=bool(s.enabled)))
        groups.append(group("Phone link", "Your Android phone and this PC, like Continuity on a Mac. "
                                          "Works only on Home networks.", link))

        if s.paired:
            phones: list[Gtk.Widget] = []
            for p in s.paired:
                # Pages are rebuilt on every refresh: keep the phones that were open, open
                row = Adw.ExpanderRow(title=p.name, subtitle=f"Paired {p.type}. Choose what it may do.",
                                      expanded=p.id in self._open_phones)
                row.connect("notify::expanded", lambda r, _p, i=p.id: (
                    self._open_phones.add(i) if r.get_expanded() else self._open_phones.discard(i)))
                for plugin, title, subtitle in PHONE_PERMISSIONS:
                    if p.supported and plugin not in p.supported:
                        continue
                    sw = Adw.SwitchRow(title=title, subtitle=subtitle, active=plugin not in p.disabled)
                    sw.connect("notify::active", lambda r, _p, ph=p, pl=plugin: self._set_permission(ph, pl, r.get_active()))
                    row.add_row(sw)
                row.add_row(button_row("Unpair", "The phone has to be paired again to connect.", "Unpair",
                                       lambda ph=p: self._confirm(f"Unpair {ph.name}?",
                                                                  "It won't be able to connect until you pair it again.",
                                                                  "Unpair", lambda: self._unpair(ph), destructive=True)))
                phones.append(row)
            groups.append(group("Paired phones", "", phones))

        screens: list[Gtk.Widget] = []
        for d in s.screens:
            where = "USB" if d.transport == "usb" else "Wi-Fi"
            if d.state == "unauthorized":
                screens.append(info_row(d.model, f"{where}: tap Allow on the phone (USB debugging), then refresh."))
                continue
            if d.state != "device":
                screens.append(info_row(d.model, f"{where}: not responding. Unplug it or reconnect."))
                continue
            row = button_row(d.model, f"Connected over {where}", "Show screen",
                             lambda serial=d.serial: self._show_screen(serial), suggested=True)
            if d.transport == "wifi":
                stop = Gtk.Button(label="Disconnect", valign=Gtk.Align.CENTER)
                stop.connect("clicked", lambda *_, serial=d.serial: self._user_cmd(
                    [PHONE, "disconnect", serial], "Phone disconnected."))
                row.add_suffix(stop)
            screens.append(row)
        if not screens:
            screens.append(info_row(
                "No phone found",
                "On the phone: Settings → About phone → tap Build number 7 times. Then Developer options → USB debugging on. "
                "Plug it in, approve it in the USB prompt and tap Allow on the phone."))
        pair = Adw.EntryRow(title="Wi-Fi pairing: address and code, e.g. 192.168.1.20:37099 123456")
        pair.set_show_apply_button(True)
        pair.connect("apply", lambda e: self._pair_wifi(e.get_text()))
        connect = Adw.EntryRow(title="Connect over Wi-Fi: address, e.g. 192.168.1.20:41235")
        connect.set_show_apply_button(True)
        connect.connect("apply", lambda e: self._user_cmd(
            [PHONE, "connect", e.get_text().strip()], "Phone connected. Press Show screen."))
        groups.append(group("Phone screen", "See and use your phone in a window, with its sound. "
                                            "Over Wi-Fi: Developer options → Wireless debugging → Pair device with pairing code.",
                            [*screens, pair, connect]))
        return groups

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
                       lambda: dialogs.show_list(self, "Connected USB devices", "", [USB, "devices"],
                                                 dialogs.parse_usb_devices, "No USB devices.")),
            button_row("Always-allowed devices", "See them, or remove one so it's asked about again.", "Show",
                       lambda: dialogs.show_list(self, "Always-allowed USB devices",
                                                 "Remove a device to be asked about it the next time it's plugged in.",
                                                 [USB, "rules"], dialogs.parse_usb_rules, "None.", self.refresh)),
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
            unlock = dialogs.Field("PASSWORD", "Current disk passphrase or recovery key")
            new_pin = [dialogs.Field("NEWPIN", "New start-up PIN", pin=True),
                       dialogs.Field("", "The same PIN again", pin=True, confirm_of="NEWPIN")]
            key_pin = dialogs.Field("PIN", "Security key PIN", pin=True)
            D = self._disk_step  # noqa: N806

            groups.append(group("Unlock at boot", "Each step asks for the passphrase you type at start-up today.", [
                button_row("Recovery key", "Create a new recovery key. Write it down and keep it away from this PC.",
                           "Create", lambda: D("Create a recovery key", "recovery-key", [unlock],
                                               "A new recovery key is shown once in the next window. Any older recovery "
                                               "key stops working.", recovery=True), suggested=True),
                button_row("Unlock automatically", "Use this PC's TPM. Breaks safely if Secure Boot is changed.",
                           "Set up", lambda: D("Unlock automatically", "tpm", [unlock],
                                               "From the next start, the drive unlocks by itself on this PC only."),
                           sensitive=s.tpm_present),
                button_row("TPM + PIN", "Type a short PIN at boot (recommended for laptops).",
                           "Set up", lambda: D("Unlock with TPM + PIN", "tpm-pin", [unlock, *new_pin],
                                               "From the next start, type this PIN instead of the passphrase."),
                           sensitive=s.tpm_present),
                button_row("Security key", "Unlock with a FIDO2 key (touch + its PIN).",
                           "Set up", lambda: D("Unlock with a security key", "fido2", [unlock, key_pin],
                                               "Plug in the key. After the password window, touch it when it blinks. "
                                               "Repeat with your backup key.",
                                               hint="Touch your security key when it blinks.")),
                button_row("Re-seal after a BIOS update", "If the drive asked for the recovery key after a firmware update.",
                           "Re-seal", lambda: D("Re-seal the TPM", "reseal", [unlock],
                                                "Type the recovery key (or passphrase) you used at start-up."),
                           sensitive=s.tpm_present),
                button_row("Show unlock methods", "List what can unlock the drive.",
                           "Show", lambda: dialogs.run(self, "Disk unlock methods", [DISK, "status"])),
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
        rows.append(button_row("Welcome to RudramOS", "Go through the first-time setup again, step by step.", "Open",
                               lambda: Gio.Subprocess.new([SETUP], Gio.SubprocessFlags.NONE)))
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

    def _key_test(self, title: str, cmd: str, body: str) -> None:
        """Strong mode on / key test: the user's password goes to PAM (pamtester) on stdin."""
        dialogs.ask(self, title, body, [dialogs.Field("PASSWORD", "Your password")], "Continue",
                    lambda v: dialogs.run(self, title, [ADMIN_MODE, cmd], stdin_text=v["PASSWORD"] + "\n",
                                          hint="Checking your password…", on_done=lambda ok, _o: self.refresh()))

    def _disk_step(self, title: str, cmd: str, fields: list[dialogs.Field], body: str,
                   recovery: bool = False, hint: str = "") -> None:
        """A pcos-disk-security step: secrets typed here, sent on stdin, never on the command line."""
        def go(values: dict[str, str]) -> None:
            def done(ok: bool, output: str) -> None:
                if ok and recovery:
                    dialogs.show_recovery_key(self, output)
                self.refresh()

            dialogs.run(self, title, [DISK, cmd, "--secrets-stdin", "--yes"], stdin_text=dialogs.secrets_text(values),
                        hint=hint or "Working… this can take a few seconds.", on_done=done)

        dialogs.ask(self, title, body, fields, "Continue", go)

    def _user_cmd(self, argv: list[str], ok_text: str) -> None:
        """Runs a command as the user (no approval needed), toasts the result, then refreshes."""
        try:
            proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        except GLib.Error as e:
            self._toast(e.message)
            return

        def done(p, result):
            try:
                _, out, _ = p.communicate_utf8_finish(result)
                ok = p.get_successful()
            except GLib.Error as e:
                ok, out = False, e.message
            if ok and ok_text:
                self._toast(ok_text)
            elif not ok:
                self._toast((out or "Something went wrong.").strip().splitlines()[-1])
            self.refresh()

        proc.communicate_utf8_async(None, None, done)

    def _set_permission(self, phone: status.PairedPhone, plugin: str, allowed: bool) -> None:
        phone.disabled = [p for p in phone.disabled if p != plugin] + ([] if allowed else [plugin])
        value = "[" + ", ".join(f"'{p}'" for p in phone.disabled) + "]" if phone.disabled else "@as []"
        self._user_cmd(["dconf", "write", f"/org/gnome/shell/extensions/gsconnect/device/{phone.id}/disabled-plugins", value], "")

    def _unpair(self, phone: status.PairedPhone) -> None:
        # GSConnect's D-Bus object path for a device: its id with non-word characters as "_"
        path = "/org/gnome/Shell/Extensions/GSConnect/Device/" + re.sub(r"\W+", "_", phone.id, flags=re.ASCII)
        try:
            Gio.bus_get_sync(Gio.BusType.SESSION, None).call_sync(
                "org.gnome.Shell.Extensions.GSConnect", path, "org.gtk.Actions", "Activate",
                GLib.Variant("(sava{sv})", ("unpair", [], {})), None, Gio.DBusCallFlags.NONE, 10000, None)
            self._toast(f"{phone.name} unpaired.")
        except GLib.Error:
            self._toast("Couldn't unpair: is Phone link on?")
        self.refresh()

    def _pair_wifi(self, text: str) -> None:
        parts = text.split()
        if len(parts) != 2:
            self._toast("Type the address and the 6-digit code shown on the phone, with a space between.")
            return
        self._user_cmd([PHONE, "pair", *parts], "Paired. Now type the address from the Wireless debugging screen below.")

    def _show_screen(self, serial: str) -> None:
        proc = Gio.Subprocess.new([PHONE, "screen", serial], Gio.SubprocessFlags.STDERR_PIPE)

        def done(p, result):
            try:
                _, _, err = p.communicate_utf8_finish(result)
            except GLib.Error as e:
                err = e.message
            # 3: pcos-phone already said why in a notification
            if not p.get_successful() and p.get_exit_status() != 3:
                self._toast((err or "The phone screen closed unexpectedly.").strip().splitlines()[-1])

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
    def __init__(self, page: str = ""):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.page = page

    def do_activate(self):
        win = self.props.active_window or Window(application=self)
        if self.page in win.pages:
            win.stack.set_visible_child_name(self.page)
        win.present()


def main() -> int:
    """pcos-control [--page updates|security|apps|phone|network|usb|privacy|disk|graphics|system]"""
    argv = list(sys.argv)
    page = ""
    if "--page" in argv:
        i = argv.index("--page")
        page = argv[i + 1] if i + 1 < len(argv) else ""
        del argv[i:i + 2]
    return App(page).run(argv)
