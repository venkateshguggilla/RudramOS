"""Tests for pcos_control.status.phone_status (Control Center → Phone).

Run: python -m unittest discover -s tests -p "test_*.py"
"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "system_files", "usr", "lib", "pcos-control"))

from pcos_control import status  # noqa: E402

DUMP = """[/]
devices=['a1b2c3', 'd4e5f6', 'gone99']
id='pc0001'
name='rudramos-pc'

[device/a1b2c3]
certificate-pem='-----BEGIN CERTIFICATE-----\\nMIIB\\n-----END CERTIFICATE-----\\n'
disabled-plugins=['mousepad', 'runcommand']
last-connection='lan://192.168.1.20:1716'
name='Pixel 7'
paired=true
supported-plugins=['battery', 'clipboard', 'mousepad', 'notification', 'runcommand', 'sms', 'telephony']
type='phone'

[device/a1b2c3/plugin/battery]
custom-battery-notification=true

[device/d4e5f6]
name='Neighbour tablet'
paired=false
type='tablet'
"""


def fake_run(outputs):
    def run(cmd, **_kwargs):
        prog = os.path.basename(cmd[0])
        if prog not in outputs:
            raise FileNotFoundError(prog)
        return SimpleNamespace(stdout=outputs[prog], returncode=0)
    return run


class PhoneStatusTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ext = os.path.join(self.dir.name, "extensions")
        os.makedirs(os.path.join(self.ext, status.GSCONNECT))

    def test_paired_phones_only(self):
        phones = status.parse_gsconnect_dump(DUMP)
        self.assertEqual([p.name for p in phones], ["Pixel 7"])  # unpaired and forgotten devices left out
        p = phones[0]
        self.assertEqual((p.id, p.type), ("a1b2c3", "phone"))
        self.assertEqual(p.disabled, ["mousepad", "runcommand"])
        self.assertIn("sms", p.supported)

    def test_empty_and_odd_dumps(self):
        self.assertEqual(status.parse_gsconnect_dump(""), [])
        self.assertEqual(status.parse_gsconnect_dump("[/]\ndevices=@as []\n"), [])
        phones = status.parse_gsconnect_dump("[/]\ndevices=['x']\n[device/x]\npaired=true\n")
        self.assertEqual((phones[0].name, phones[0].supported, phones[0].disabled), ("Phone", [], []))

    def test_full_status(self):
        run = fake_run({
            "gnome-extensions": "gsconnect@andyholmes.github.io\n  Name: GSConnect\n  Enabled: Yes\n  State: ACTIVE\n",
            "dconf": DUMP,
            "pcos-phone": "R58M12345ABC\tdevice\tusb\tSM G973F\n192.168.1.20:41235\tunauthorized\twifi\tPixel 7\n",
        })
        s = status.phone_status(extensions_dir=self.ext, phone_tool="/usr/bin/pcos-phone", run=run)
        self.assertTrue(s.installed)
        self.assertTrue(s.enabled)
        self.assertEqual(len(s.paired), 1)
        self.assertEqual([(d.serial, d.state, d.transport, d.model) for d in s.screens],
                         [("R58M12345ABC", "device", "usb", "SM G973F"),
                          ("192.168.1.20:41235", "unauthorized", "wifi", "Pixel 7")])

    def test_switched_off(self):
        run = fake_run({"gnome-extensions": "  Enabled: No\n  State: INACTIVE\n", "dconf": "", "pcos-phone": ""})
        s = status.phone_status(extensions_dir=self.ext, run=run)
        self.assertFalse(s.enabled)
        self.assertEqual((s.paired, s.screens), ([], []))

    def test_tools_missing(self):
        s = status.phone_status(extensions_dir=self.ext, run=fake_run({}))
        self.assertTrue(s.installed)
        self.assertIsNone(s.enabled)
        self.assertEqual(s.screens, [])

    def test_gsconnect_not_installed(self):
        s = status.phone_status(extensions_dir=os.path.join(self.dir.name, "none"), run=fake_run({"pcos-phone": ""}))
        self.assertFalse(s.installed)
        self.assertIsNone(s.enabled)


if __name__ == "__main__":
    unittest.main()
