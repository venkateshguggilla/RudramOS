"""Dialogs for the steps that used to open a terminal: typing a passphrase or PIN, touching a
security key, reading a new recovery key, and the "Show" lists.

Secrets go to the RudramOS tools on stdin (never on the command line, where other programs can
read them) and are never shown or logged. The tools run through pkexec, so the system's own
admin prompt still appears first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

# systemd-cryptenroll recovery keys: 8 groups of 8 "modhex" characters
RECOVERY_KEY = re.compile(r"\b(?:[cbdefghijklnrtuv]{8}-){7}[cbdefghijklnrtuv]{8}\b")
TOUCH = re.compile(r"touch|presence|blink", re.I)
CANCELLED = (126, 127)  # pkexec: approval dismissed / not authorized


@dataclass
class Field:
    key: str  # name sent to the tool (PASSWORD, NEWPIN, PIN) or "" for a confirmation copy
    title: str
    pin: bool = False  # digits only, at least 4
    confirm_of: str = ""  # must equal the field with this key


def secrets_text(values: dict[str, str]) -> str:
    """KEY=value lines for a tool's --secrets-stdin (or just the password for PAM tools)."""
    return "".join(f"{k}={v}\n" for k, v in values.items() if k)


def check_fields(fields: list[Field], values: dict[str, str]) -> str:
    """"" when the entries are fine, else what to fix (shown under the entries)."""
    for f in fields:
        v = values.get(f.title, "")
        if not v:
            return ""  # still typing: keep the button off, no message yet
        if f.pin and (not v.isdigit() or len(v) < 4):
            return f"{f.title}: at least 4 digits."
        if f.confirm_of:
            other = next(o for o in fields if o.key == f.confirm_of)
            if v != values.get(other.title, ""):
                return "The two PINs are different."
        if "\n" in v:
            return "Line breaks aren't allowed."
    return ""


def ask(parent: Gtk.Widget, heading: str, body: str, fields: list[Field], action: str,
        on_ok: Callable[[dict[str, str]], None]) -> None:
    """Asks for passphrases / PINs; on_ok gets {key: value} for fields with a key."""
    dialog = Adw.AlertDialog(heading=heading, body=body)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    rows.add_css_class("boxed-list")
    entries: dict[str, Adw.PasswordEntryRow] = {}
    for f in fields:
        row = Adw.PasswordEntryRow(title=f.title)
        if f.pin:
            row.set_input_purpose(Gtk.InputPurpose.PIN)
        entries[f.title] = row
        rows.append(row)
    hint = Gtk.Label(wrap=True, xalign=0)
    hint.add_css_class("error")
    box.append(rows)
    box.append(hint)
    dialog.set_extra_child(box)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("go", action)
    dialog.set_response_appearance("go", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("go")
    dialog.set_close_response("cancel")

    def values() -> dict[str, str]:
        return {title: e.get_text() for title, e in entries.items()}

    def update(*_):
        v = values()
        problem = check_fields(fields, v)
        hint.set_text(problem)
        dialog.set_response_enabled("go", not problem and all(v.values()))

    for e in entries.values():
        e.connect("changed", update)
    update()

    def respond(_d, response):
        v = values()
        for e in entries.values():
            e.set_text("")
        if response == "go" and not check_fields(fields, v) and all(v.values()):
            on_ok({f.key: v[f.title] for f in fields if f.key})

    dialog.connect("response", respond)
    dialog.present(parent)


def run(parent: Gtk.Widget, title: str, argv: list[str], stdin_text: str = "", hint: str = "",
        on_done: Callable[[bool, str], None] | None = None, hide_output: bool = False) -> None:
    """Runs pkexec argv in a progress dialog: what the tool says (recovery keys masked), a
    "touch your key" notice when it asks for one, and the result. on_done(ok, full output)."""
    dialog = Adw.AlertDialog(heading=title, body="Approve in the system's password window first.")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    status = Gtk.Box(spacing=8)
    spinner = Gtk.Spinner(spinning=True)
    state = Gtk.Label(label=hint or "Working…", wrap=True, xalign=0, hexpand=True)
    status.append(spinner)
    status.append(state)
    out_label = Gtk.Label(wrap=True, xalign=0, selectable=True, visible=not hide_output)
    out_label.add_css_class("monospace")
    out_label.add_css_class("dim-label")
    scroll = Gtk.ScrolledWindow(child=out_label, min_content_height=120, max_content_height=260,
                                propagate_natural_height=True, visible=not hide_output)
    box.append(status)
    box.append(scroll)
    dialog.set_extra_child(box)
    dialog.add_response("close", "Close")
    dialog.set_response_enabled("close", False)
    dialog.present(parent)

    lines: list[str] = []
    try:
        proc = Gio.Subprocess.new(["pkexec", *argv], Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE
                                  | Gio.SubprocessFlags.STDERR_MERGE)
    except GLib.Error as e:
        state.set_text(e.message)
        spinner.set_spinning(False)
        dialog.set_response_enabled("close", True)
        return
    stdin = proc.get_stdin_pipe()
    if stdin_text:
        stdin.write_all(stdin_text.encode(), None)
    stdin.close(None)
    reader = Gio.DataInputStream(base_stream=proc.get_stdout_pipe())

    def show_line(line: str) -> None:
        lines.append(line)
        shown = [RECOVERY_KEY.sub("•••••••• (shown in the next window)", x) for x in lines[-40:]]
        out_label.set_text("\n".join(shown).strip())
        dialog.set_body("")
        if TOUCH.search(line):
            state.set_markup("<b>Touch your security key now</b> (it blinks).")

    def read_next(stream, result):
        try:
            data, _ = stream.read_line_finish_utf8(result)
        except GLib.Error:
            data = None
        if data is None:
            proc.wait_async(None, finished)
            return
        show_line(data)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, read_next)

    def finished(p, result):
        try:
            p.wait_finish(result)
        except GLib.Error:
            pass
        ok = p.get_successful()
        code = p.get_exit_status() if p.get_if_exited() else -1
        spinner.set_spinning(False)
        if ok:
            state.set_markup("<b>Done.</b>")
        elif code in CANCELLED:
            state.set_text("Cancelled: nothing was changed.")
        else:
            last = next((x for x in reversed(lines) if x.strip()), "")
            state.set_markup("<b>That didn't work.</b> " + GLib.markup_escape_text(last))
        dialog.set_response_enabled("close", True)
        if on_done:
            on_done(ok, "\n".join(lines))

    reader.read_line_async(GLib.PRIORITY_DEFAULT, None, read_next)


def show_recovery_key(parent: Gtk.Widget, output: str) -> None:
    """The new recovery key, once, with Copy, until the user says it's written down."""
    m = RECOVERY_KEY.search(output)
    if not m:
        return
    key = m.group(0)
    dialog = Adw.AlertDialog(
        heading="Your new recovery key",
        body="Write it down or print it now, and keep it away from this PC. It's shown only this once. "
             "It unlocks the drive if the TPM or your security key ever can't.")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    label = Gtk.Label(label=key, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.CHAR)
    label.add_css_class("title-3")
    label.add_css_class("monospace")
    copy = Gtk.Button(label="Copy", halign=Gtk.Align.CENTER)
    copy.connect("clicked", lambda *_: Gdk.Display.get_default().get_clipboard().set(key))
    box.append(label)
    box.append(copy)
    dialog.set_extra_child(box)
    dialog.add_response("done", "I've written it down")
    dialog.set_can_close(False)  # only the button closes it, not Esc or a click outside
    dialog.connect("response", lambda d, _r: (d.set_can_close(True), d.close()))
    dialog.present(parent)


@dataclass
class Item:
    title: str
    subtitle: str = ""
    remove: list[str] | None = None  # pkexec argv that removes it, or None


def parse_approved_programs(output: str) -> list[Item]:
    items = []
    for line in output.splitlines():
        path = line.strip()
        if path.startswith("/"):
            items.append(Item(GLib.path_get_basename(path), GLib.path_get_dirname(path),
                              ["/usr/bin/pcos-app-guard", "revoke", path]))
    return items


USB_RULE = re.compile(r'^\s*(\d+):\s*(allow|block|reject)\b(.*)$')


def parse_usb_rules(output: str) -> list[Item]:
    items = []
    for line in output.splitlines():
        m = USB_RULE.match(line)
        if not m:
            continue
        num, target, rest = m.groups()
        name = re.search(r'\bname "([^"]*)"', rest)
        dev = re.search(r'\bid ([0-9a-f*]{4}:[0-9a-f*]{4})', rest)
        if dev:
            title = (name.group(1) if name and name.group(1) else "") or f"USB device {dev.group(1)}"
            ifaces = re.search(r"with-interface (\{[^}]*\}|\S+)", rest)
            # interface "class:subclass:protocol" triples, e.g. 09:00:00 (hub), 03:01:01 (keyboard)
            classes = re.findall(r"\b([0-9a-f*]{2}):[0-9a-f*]{2}:[0-9a-f*]{2}\b", ifaces.group(1)) if ifaces else []
            if classes and all(c == "09" for c in classes):
                # A hub or the PC's own USB controller: every port depends on it, so no Remove
                items.append(Item(title, f"USB hub or controller · {dev.group(1)} · always allowed"))
                continue
            items.append(Item(title, f"{'Always allowed' if target == 'allow' else 'Always blocked'} · {dev.group(1)}",
                              ["/usr/bin/pcos-usb", "forget", num]))
        elif "with-interface" in rest and target == "allow":
            items.append(Item("Plain keyboards and mice", "Built-in rule: so you're never locked out at login"))
        else:
            items.append(Item(rest.strip()[:60] or target, "Built-in rule"))
    return items


def parse_usb_devices(output: str) -> list[Item]:
    items = []
    for line in output.splitlines():
        m = re.match(r"^\s*(\d+)\s+(\S+)\s+(.*)$", line)
        if m:
            _id, target, desc = m.groups()
            state = {"allow": "Allowed", "block": "Blocked", "reject": "Rejected"}.get(target, target)
            items.append(Item(desc, state))
    return items


def show_list(parent: Gtk.Widget, title: str, description: str, argv: list[str],
              parse: Callable[[str], list[Item]], empty: str, on_change: Callable[[], None] | None = None) -> None:
    """A list from a RudramOS tool (through pkexec), with Remove buttons where possible."""
    dialog = Adw.AlertDialog(heading=title, body=description)
    rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    rows.add_css_class("boxed-list")
    scroll = Gtk.ScrolledWindow(child=rows, min_content_height=80, max_content_height=380,
                                propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    dialog.set_extra_child(scroll)
    dialog.add_response("close", "Close")
    dialog.present(parent)

    def fill(items: list[Item] | None, error: str = "") -> None:
        while (child := rows.get_first_child()) is not None:
            rows.remove(child)
        if items is None:
            rows.append(Adw.ActionRow(title=error or "Loading…"))
            return
        if not items:
            rows.append(Adw.ActionRow(title=empty))
        for it in items:
            row = Adw.ActionRow(title=GLib.markup_escape_text(it.title), subtitle=GLib.markup_escape_text(it.subtitle))
            if it.remove:
                button = Gtk.Button(label="Remove", valign=Gtk.Align.CENTER)
                button.add_css_class("destructive-action")
                button.connect("clicked", lambda b, argv=it.remove: remove(b, argv))
                row.add_suffix(button)
            rows.append(row)

    def load() -> None:
        fill(None)
        proc = Gio.Subprocess.new(["pkexec", *argv], Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)

        def done(p, result):
            try:
                _, out, _ = p.communicate_utf8_finish(result)
            except GLib.Error as e:
                fill(None, e.message)
                return
            if p.get_successful():
                fill(parse(out or ""))
            elif p.get_exit_status() in CANCELLED:
                fill(None, "Cancelled.")
            else:
                fill(None, (out or "Couldn't read the list.").strip().splitlines()[-1])

        proc.communicate_utf8_async(None, None, done)

    def remove(button: Gtk.Button, argv_remove: list[str]) -> None:
        button.set_sensitive(False)
        proc = Gio.Subprocess.new(["pkexec", *argv_remove], Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)

        def done(p, result):
            try:
                p.communicate_utf8_finish(result)
            except GLib.Error:
                pass
            if on_change:
                on_change()
            load()

        proc.communicate_utf8_async(None, None, done)

    load()
