#!/usr/bin/python3
"""Screenshots of Control Center and its dialogs, for checking the UI without a PC.

Runs inside the RudramOS image on a virtual screen (see .github/workflows/ui-screenshots.yml):
opens every Control Center page and each dialog, with a fake pkexec on PATH that prints what the
real tools would, and saves a PNG of the screen after each step into $OUT (default ./shots).
Nothing is changed: the fake pkexec never runs the real tools.

Usage: ui-demo.py <path to pcos-control lib dir>
"""

import os
import subprocess
import sys

sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else "/usr/lib/pcos-control")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib  # noqa: E402

from pcos_control import app, dialogs, setup  # noqa: E402

OUT = os.environ.get("OUT", "shots")
os.makedirs(OUT, exist_ok=True)
STEP_MS = 2500


def shot(name: str) -> None:
    subprocess.run(["import", "-window", "root", os.path.join(OUT, f"{name}.png")], check=False)
    print("shot", name, flush=True)


def type_into(dialog_owner, texts: list[str]) -> None:
    """Fill the password rows of the dialog that's open now."""
    dlg = dialog_owner.get_visible_dialog()
    rows = []

    def walk(w):
        if isinstance(w, Adw.PasswordEntryRow):
            rows.append(w)
        child = w.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(dlg)
    for row, text in zip(rows, texts):
        row.set_text(text)


def close_dialogs(win) -> None:
    dlg = win.get_visible_dialog()
    while dlg is not None:
        dlg.set_can_close(True)
        dlg.force_close()
        dlg = win.get_visible_dialog()


def main() -> int:
    application = Adw.Application(application_id="org.pcos.UiDemo")
    steps = []

    def activate(a):
        win = app.Window(application=a)
        win.set_default_size(1100, 800)
        win.present()
        for page in win.pages:
            steps.append((f"page-{page}", lambda p=page: win.stack.set_visible_child_name(p)))
        steps.append(("disk-tpm-pin-ask", lambda: (win.stack.set_visible_child_name("disk"), win._disk_step(
            "Unlock with TPM + PIN", "tpm-pin",
            [dialogs.Field("PASSWORD", "Current disk passphrase or recovery key"),
             dialogs.Field("NEWPIN", "New start-up PIN", pin=True),
             dialogs.Field("", "The same PIN again", pin=True, confirm_of="NEWPIN")],
            "From the next start, type this PIN instead of the passphrase."))))
        steps.append(("disk-tpm-pin-typed-mismatch", lambda: type_into(win, ["my passphrase", "4821", "4822"])))
        steps.append(("disk-tpm-pin-typed-ok", lambda: type_into(win, ["my passphrase", "4821", "4821"])))
        steps.append(("security-key-touch", lambda: (close_dialogs(win), dialogs.run(
            win, "Register a security key", [app.ADMIN_MODE, "add-key"],
            hint="Plug in the key. After the password window, touch it when it blinks."))))
        steps.append(("security-key-done", lambda: None))
        steps.append(("recovery-key-progress", lambda: (close_dialogs(win), dialogs.run(
            win, "Create a recovery key", [app.DISK, "recovery-key", "--secrets-stdin", "--yes"],
            stdin_text="PASSWORD=x\n", on_done=lambda ok, out: dialogs.show_recovery_key(win, out) if ok else None))))
        steps.append(("recovery-key-shown", lambda: None))
        steps.append(("list-approved-programs", lambda: (close_dialogs(win), dialogs.show_list(
            win, "Approved programs", "These run from Downloads, the Desktop or USB drives. Remove one to block it again.",
            [app.APP_GUARD, "list"], dialogs.parse_approved_programs, "No programs approved yet."))))
        steps.append(("list-usb-rules", lambda: (close_dialogs(win), dialogs.show_list(
            win, "Always-allowed USB devices", "Remove a device to be asked about it the next time it's plugged in.",
            [app.USB, "rules"], dialogs.parse_usb_rules, "None."))))
        steps.append(("failed-step", lambda: (close_dialogs(win), dialogs.run(
            win, "Unlock automatically", [app.DISK, "tpm", "--secrets-stdin", "--yes"], stdin_text="PASSWORD=wrong\n"))))

        def setup_window():
            close_dialogs(win)
            sw = setup.SetupWindow(["welcome", "admin", "disk", "privacy", "protect", "done"], application=a)
            sw.present()
            win.setup_window = sw

        steps.append(("setup-welcome", setup_window))
        for i in range(1, 6):
            steps.append((f"setup-step-{i + 1}", lambda: win.setup_window.go(win.setup_window.index + 1)))
        steps.append(("end", lambda: a.quit()))

        def run_step():
            name, action = steps.pop(0)
            if name == "end":
                action()
                return GLib.SOURCE_REMOVE
            action()
            GLib.timeout_add(STEP_MS, lambda: (shot(name), GLib.SOURCE_REMOVE)[1])
            GLib.timeout_add(STEP_MS + 300, run_step)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(4000, run_step)

    application.connect("activate", activate)
    return application.run([])


if __name__ == "__main__":
    sys.exit(main())
