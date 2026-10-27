"""Tests for the logic in pcos_control.dialogs (no GTK needed: gi is stubbed).

Run: python -m unittest discover -s tests -p "test_*.py"
"""

import os
import sys
import types
import unittest

# Stand-ins for gi, so the module imports on machines without GTK / libadwaita
_gi = types.ModuleType("gi")
_gi.require_version = lambda *a: None
_repo = types.ModuleType("gi.repository")
for _name in ("Adw", "Gdk", "Gio", "Gtk", "Pango"):
    setattr(_repo, _name, types.SimpleNamespace())
_repo.GLib = types.SimpleNamespace(path_get_basename=os.path.basename, path_get_dirname=os.path.dirname)
sys.modules["gi"] = _gi  # replace a real gi too: CI machines may have gi without libadwaita
sys.modules["gi.repository"] = _repo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "system_files", "usr", "lib", "pcos-control"))

from pcos_control import dialogs  # noqa: E402

F = dialogs.Field
PIN_FIELDS = [F("PASSWORD", "Passphrase"), F("NEWPIN", "PIN", pin=True), F("", "PIN again", pin=True, confirm_of="NEWPIN")]


class FieldTests(unittest.TestCase):
    def test_complete_and_matching(self):
        self.assertEqual(dialogs.check_fields(PIN_FIELDS, {"Passphrase": "x y", "PIN": "4821", "PIN again": "4821"}), "")

    def test_still_typing_shows_no_error(self):
        self.assertEqual(dialogs.check_fields(PIN_FIELDS, {"Passphrase": "", "PIN": "", "PIN again": ""}), "")

    def test_pin_rules(self):
        self.assertIn("4 digits", dialogs.check_fields(PIN_FIELDS, {"Passphrase": "p", "PIN": "12", "PIN again": "12"}))
        self.assertIn("4 digits", dialogs.check_fields(PIN_FIELDS, {"Passphrase": "p", "PIN": "12ab", "PIN again": "12ab"}))
        self.assertIn("different", dialogs.check_fields(PIN_FIELDS, {"Passphrase": "p", "PIN": "4821", "PIN again": "4822"}))

    def test_no_line_breaks(self):
        self.assertIn("Line breaks", dialogs.check_fields([F("PASSWORD", "P")], {"P": "a\nNEWPIN=1"}))

    def test_secrets_text_skips_confirmation_copies(self):
        self.assertEqual(dialogs.secrets_text({"PASSWORD": "a=b c", "NEWPIN": "4821", "": "4821"}),
                         "PASSWORD=a=b c\nNEWPIN=4821\n")


class OutputTests(unittest.TestCase):
    KEY = "fvgldvhk-kbjjdcuv-rudtcltk-hfiunrhu-tjlcjhrb-hrijrvbt-inrbcklh-ijbreeiv"

    def test_recovery_key_found_and_masked_pattern(self):
        out = f"A secret recovery key has been generated for this volume:\n\n    🔐 {self.KEY}\n\nPlease save it."
        self.assertEqual(dialogs.RECOVERY_KEY.search(out).group(0), self.KEY)
        self.assertIsNone(dialogs.RECOVERY_KEY.search("abcdefgh-" * 7 + "abcdefgh"))  # a, g... aren't modhex

    def test_touch_prompts(self):
        for line in ("Please touch the device.", "Please confirm presence on security token to unlock.",
                     "Touch the key when it blinks"):
            self.assertTrue(dialogs.TOUCH.search(line), line)
        self.assertFalse(dialogs.TOUCH.search("New TPM2 token enrolled as key slot 2."))


class ListTests(unittest.TestCase):
    def test_approved_programs(self):
        items = dialogs.parse_approved_programs("/home/venky/Downloads/tool.AppImage\n\n/run/media/x/app\n")
        self.assertEqual([(i.title, i.subtitle) for i in items],
                         [("tool.AppImage", "/home/venky/Downloads"), ("app", "/run/media/x")])
        self.assertEqual(items[0].remove, ["/usr/bin/pcos-app-guard", "revoke", "/home/venky/Downloads/tool.AppImage"])

    def test_usb_rules(self):
        out = ('1: allow id 1d6b:0002 serial "0000:00:14.0" name "xHCI Host Controller" hash "abc=" with-interface 09:00:00\n'
               '2: allow id 046d:c31c serial "" name "USB Keyboard" hash "def=" with-interface { 03:01:01 03:00:00 }\n'
               '3: allow id 1050:0407 serial "" name "" hash "ghi="\n'
               '4: allow with-interface match-all { 03:01:01 03:00:01 } if !allowed-matches(with-interface one-of { 03:01:01 })\n')
        items = dialogs.parse_usb_rules(out)
        self.assertEqual(items[1].title, "USB Keyboard")
        self.assertEqual(items[1].remove, ["/usr/bin/pcos-usb", "forget", "2"])
        self.assertEqual(items[2].title, "USB device 1050:0407")
        self.assertEqual(items[3].title, "Plain keyboards and mice")
        self.assertIsNone(items[3].remove)  # built-in rule: can't be removed here

    def test_usb_devices(self):
        out = "1    allow  Logitech USB Keyboard: Keyboard\n7    block  SanDisk Cruzer: Storage [danger]\nnoise\n"
        items = dialogs.parse_usb_devices(out)
        self.assertEqual([(i.title, i.subtitle) for i in items],
                         [("Logitech USB Keyboard: Keyboard", "Allowed"), ("SanDisk Cruzer: Storage [danger]", "Blocked")])


if __name__ == "__main__":
    unittest.main()
