"""Welcome to RudramOS: the first-boot setup (docs/DESIGN.md §10).

Opens once at an admin's first login (autostart: pcos-setup --first-login) and any time from the
app grid. One step per page, with Back / Next. The steps reuse Control Center's pages, so the
buttons, admin approval and terminal steps are the same in both. Closing early is fine: it opens
again at the next login until Finish (or Skip setup) is pressed.
"""

from __future__ import annotations

import os
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import firstboot, status  # noqa: E402
from .app import CONTROL_CENTER, Window, button_row, group, info_row  # noqa: E402

SETUP_ID = "org.pcos.Setup"

TITLES = {
    "welcome": "Welcome",
    "admin": "Admin approval",
    "disk": "Disk encryption",
    "privacy": "Privacy",
    "network": "This network",
    "graphics": "Graphics driver",
    "phone": "Your phone",
    "protect": "Protect this PC",
    "done": "All set",
}


def context() -> firstboot.Context:
    disk = status.disk_status()
    gfx = status.graphics_status()
    return firstboot.Context(
        encrypted=disk.encrypted,
        nvidia=gfx.installed.startswith("rudramos-nvidia"),
        driver_needed=gfx.wanted != gfx.installed,
        mok=firstboot.mok_state(disk.secure_boot),
        networks=len(status.network_status().networks),
        phone_link=status.phone_status().installed,
    )


class SetupWindow(Window):
    """Control Center's page builders in a step-by-step window."""

    def __init__(self, steps: list[str], **kwargs):
        # Not Window.__init__: no page tabs here, only the state its page builders use
        Adw.ApplicationWindow.__init__(self, title="Welcome to RudramOS", default_width=720, default_height=640, **kwargs)
        self.steps = steps
        self.index = 0
        self._loading = False
        self._operation = None
        self._poll_id = 0
        self._started_here = False
        self._updating = False
        self._open_phones: set[str] = set()

        self.page = Adw.PreferencesPage()
        self.groups: list[Gtk.Widget] = []
        self.toasts = Adw.ToastOverlay(child=self.page)

        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle()
        header.set_title_widget(self.title)

        self.back = Gtk.Button(label="Back")
        self.back.connect("clicked", lambda *_: self.go(self.index - 1))
        self.next = Gtk.Button(label="Next")
        self.next.add_css_class("suggested-action")
        self.next.connect("clicked", lambda *_: self.go(self.index + 1))
        bar = Gtk.ActionBar()
        bar.pack_start(self.back)
        bar.pack_end(self.next)

        toolbar = Adw.ToolbarView(content=self.toasts)
        toolbar.add_top_bar(header)
        toolbar.add_bottom_bar(bar)
        self.set_content(toolbar)
        # Refresh when the window comes back into focus, e.g. after a terminal step finishes
        self.connect("notify::is-active", lambda *_: self.refresh() if self.is_active() else None)
        self.go(0)

    # ---- navigation ----

    def go(self, index: int) -> None:
        if index >= len(self.steps):
            self.finish()
            return
        self.index = max(0, index)
        step = self.steps[self.index]
        self.title.set_title(TITLES.get(step, step))
        self.title.set_subtitle(f"Step {self.index + 1} of {len(self.steps)}")
        self.back.set_visible(0 < self.index < len(self.steps) - 1)
        self.next.set_label({"welcome": "Start", "done": "Finish"}.get(step, "Next"))
        self.refresh()

    def finish(self) -> None:
        firstboot.mark_done()
        self.close()

    # ---- content: loaded in a thread (status readers can take a moment) ----

    def refresh(self, check_online: bool = False) -> None:
        if self._loading:
            return
        self._loading = True
        step = self.steps[self.index]

        def load():
            data = {"operation": status.system_operation()}
            if step == "admin":
                data["admin"] = status.admin_status()
            elif step == "disk":
                data["disk"] = status.disk_status()
            elif step == "privacy":
                data["privacy"] = status.privacy_status()
            elif step == "network":
                data["network"] = status.network_status()
            elif step == "graphics":
                data["graphics"] = status.graphics_status()
                data["updates"] = status.update_status(check_online=False)
                data["mok"] = firstboot.mok_state(status.disk_status().secure_boot)
            elif step == "phone":
                data["phone"] = status.phone_status()
                data["network"] = status.network_status()
            GLib.idle_add(self._show, step, data)

        threading.Thread(target=load, daemon=True).start()

    def _show(self, step: str, data: dict) -> bool:
        self._loading = False
        if step != self.steps[self.index]:  # moved on while loading
            self.refresh()
            return GLib.SOURCE_REMOVE
        self._operation = data["operation"]
        if self._operation and not self._poll_id:
            self._poll_id = GLib.timeout_add_seconds(5, self._poll)
        for g in self.groups:
            self.page.remove(g)
        self.groups = getattr(self, f"_step_{step}")(data)
        for g in self.groups:
            self.page.add(g)
        return GLib.SOURCE_REMOVE

    # ---- the steps ----

    def _step_welcome(self, _data) -> list[Gtk.Widget]:
        hello = Adw.PreferencesGroup()
        hello.add(Adw.StatusPage(
            icon_name="rudramos-logo", title="Welcome to RudramOS",
            description="A few choices to make this PC safe and yours. It takes about five minutes, and "
                        "everything can be changed later in RudramOS Control Center.\n\n"
                        "Close this window to finish later: it opens again when you next log in."))
        skip = group("", "", [button_row("Skip setup", "You can open it again any time: Welcome to RudramOS in the app grid.",
                                         "Skip", self.finish)])
        return [hello, skip]

    def _step_admin(self, data) -> list[Gtk.Widget]:
        intro = group("How should installs and system changes be approved?",
                      "Standard asks for your password, like a Mac. Strong also needs a touch of a USB security key "
                      "(e.g. YubiKey), so a stolen password alone isn't enough. Register two keys: one is a backup. "
                      "If you have no security key, keep Standard.", [])
        return [intro, *self._security(data["admin"])]

    def _step_disk(self, data) -> list[Gtk.Widget]:
        d: status.DiskStatus = data["disk"]
        if not d.encrypted:
            return [group("This drive isn't encrypted",
                          "Anyone who takes the drive out can read your files. Encryption is chosen when installing "
                          "(\"Encrypt my data\"). To turn it on, back up your files and reinstall RudramOS with it ticked.",
                          [info_row("TPM 2.0 chip", "Present" if d.tpm_present else "Not found")])]
        intro = group("Keep your files safe if the PC is stolen",
                      "1. Create a recovery key and write it down (or print it). Keep it away from this PC: it's the "
                      "only way in if the PC's TPM chip or your security key stops working.\n"
                      "2. Choose how the drive unlocks at start-up: automatically with this PC's TPM (desktops), "
                      "TPM + a short PIN (laptops), or a security key.", [])
        return [intro, *self._disk(d)]

    def _step_privacy(self, data) -> list[Gtk.Widget]:
        presets = self._privacy(data["privacy"])[0]  # just the presets; the details are in Control Center
        return [presets, group("", "Fine-tune DNS, tracker blocking, logs and the VPN kill switch in "
                                   "Control Center → Privacy.", [])]

    def _step_network(self, data) -> list[Gtk.Widget]:
        networks = self._network(data["network"])[0]
        networks.set_title("Is this your home network?")
        networks.set_description("Public (the default): nothing on the network can reach this PC. Choose Home only "
                                 "for your own Wi-Fi: then sharing you turn on (phone, printers, files) can work there.")
        return [networks]

    def _step_graphics(self, data) -> list[Gtk.Widget]:
        groups = self._graphics(data["graphics"], data["updates"])
        mok = data["mok"]
        if mok in ("missing", "pending"):
            groups.append(group("One blue screen after the restart", "", [info_row(
                "Allow the NVIDIA driver to load (Secure Boot)",
                "After restarting, a blue \"MOK Manager\" screen appears once. Choose Enroll MOK → Continue → Yes, "
                "type the password universalblue (nothing shows while typing), then Reboot."
                + ("" if mok == "pending" else " The driver install arranges this; if the screen never appears, "
                                                "reinstall the driver from Control Center → Graphics."))]))
        return groups

    def _step_phone(self, data) -> list[Gtk.Widget]:
        link = self._phone(data["phone"], data["network"])[0]
        link.set_description("Optional: skip this if you don't use an Android phone. Notifications, texts, calls, "
                             "files and clipboard, like Continuity on a Mac. More in Control Center → Phone.")
        return [link]

    def _step_protect(self, _data) -> list[Gtk.Widget]:
        firmware = group("Settings only the BIOS can change",
                         "They stop someone with the PC in hand from starting another system to get around RudramOS.", [
                             info_row("Set a BIOS / UEFI password",
                                      "So nobody can change start-up settings or turn Secure Boot off. Write it down."),
                             info_row("Start only from this drive",
                                      "Turn off starting from USB drives (or put this drive first and lock the order "
                                      "with the BIOS password)."),
                             info_row("Keep Secure Boot and TPM on",
                                      "Disk unlock with the TPM depends on them."),
                             button_row("Open the BIOS settings now", "The PC restarts. Save your work first.",
                                        "Restart…", self._confirm_firmware_restart),
                         ])
        always = group("Already taken care of", "", [
            info_row("Updates", "Download in the background and start after a restart. Control Center → Updates."),
            info_row("New USB devices", "Blocked until you allow them in the notification."),
            info_row("Downloaded programs", "Run only after you approve them (Control Center → Apps)."),
        ])
        return [firmware, always]

    def _step_done(self, _data) -> list[Gtk.Widget]:
        done = Adw.PreferencesGroup()
        done.add(Adw.StatusPage(icon_name="emblem-ok-symbolic", title="RudramOS is ready",
                                description="Everything you set here can be changed in RudramOS Control Center."))
        more = group("", "", [button_row("RudramOS Control Center", "All security and system settings.", "Open",
                                         lambda: Gio.Subprocess.new([CONTROL_CENTER], Gio.SubprocessFlags.NONE))])
        return [done, more]


class SetupApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=SETUP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.steps: list[str] = []

    def do_activate(self):
        win = self.props.active_window or SetupWindow(self.steps, application=self)
        win.present()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--reset" in argv:
        try:
            os.remove(firstboot.marker())
        except OSError:
            pass
        print("Setup will open again at the next login.")
        return 0
    if "--first-login" in argv:
        argv.remove("--first-login")
        if not firstboot.should_start():
            return 0
        # Let GNOME's own first-login setup (language, accounts) finish first
        waited = 0
        while firstboot.initial_setup_running() and waited < 3600:
            time.sleep(5)
            waited += 5
    app = SetupApp()
    app.steps = firstboot.steps(context())
    return app.run(argv)
