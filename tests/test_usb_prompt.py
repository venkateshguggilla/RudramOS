"""Tests for the logic of system_files/usr/libexec/pcos/pcos-usb-prompt (the USB popup).

Run: python -m unittest discover -s tests -p "test_*.py"
"""

import importlib.machinery
import importlib.util
import os
import tempfile
import unittest

PATH = os.path.join(os.path.dirname(__file__), "..", "system_files", "usr", "libexec", "pcos", "pcos-usb-prompt")
_loader = importlib.machinery.SourceFileLoader("pcos_usb_prompt", PATH)
_spec = importlib.util.spec_from_loader("pcos_usb_prompt", _loader)
prompt = importlib.util.module_from_spec(_spec)
_loader.exec_module(prompt)

RULE = ('7: block id 0781:5581 serial "4C53" name "Ultra Fit" hash "x" parent-hash "y" via-port "2-1" '
        'with-interface 08:06:50 with-connect-type "hotplug"')


class PopupTests(unittest.TestCase):
    def test_new_drive(self):
        title, body, actions, urgency = prompt.popup("Storage", "Ultra Fit", "ok", "Allow it if it's yours.")
        self.assertEqual(title, "USB device connected")
        self.assertIn("<b>Ultra Fit</b>", body)
        self.assertIn("Storage.", body)
        self.assertEqual(actions[0], ("open", "Open"))  # Open first: it asks for the password
        self.assertEqual([a for a, _ in actions], ["open", "always", "block"])
        self.assertEqual(urgency, "normal")

    def test_keyboard_is_allowed_not_opened(self):
        _, _, actions, _ = prompt.popup("Keyboard", "USB Keyboard", "caution", "It can type on this computer.")
        self.assertEqual(actions[0], ("open", "Allow"))

    def test_phone_opens_in_files(self):
        _, _, actions, _ = prompt.popup("Camera/phone (photos)", "Pixel 8", "ok", "")
        self.assertEqual(actions[0], ("open", "Open"))

    def test_suspicious(self):
        title, _, actions, urgency = prompt.popup("Keyboard + Storage", "Flash Disk", "danger", "Block it.")
        self.assertTrue(title.startswith("⚠"))
        self.assertEqual(actions, [("open", "Open anyway"), ("block", "Keep blocked")])
        self.assertEqual(urgency, "critical")

    def test_security_key(self):
        _, _, actions, _ = prompt.popup("Security key", "YubiKey", "ok", "")
        self.assertEqual(actions[0], ("always", "Allow"))

    def test_already_allowed_drive(self):
        title, body, actions, _ = prompt.popup("Storage", "PHOTOS", "ok", "", allowed=True)
        self.assertEqual(title, "USB drive connected")
        self.assertIn("Already allowed", body)
        self.assertEqual(actions, [("open", "Open")])

    def test_device_names_cant_inject_markup(self):
        _, body, _, _ = prompt.popup("Storage", '<a href="https://evil">Click</a> & more', "ok", "")
        self.assertNotIn("<a ", body)
        self.assertIn("&lt;a href", body)
        self.assertIn("&amp; more", body)


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.sys = self.dir.name

    def mk(self, *parts):
        os.makedirs(os.path.join(self.sys, *parts), exist_ok=True)

    def test_port_of_rule(self):
        self.assertEqual(prompt.port_of(RULE), "2-1")
        self.assertEqual(prompt.port_of('3: block id 1:2 via-port "1-4.2"'), "1-4.2")
        self.assertEqual(prompt.port_of('3: block id 1:2 name "via-port \\"9-9\\""'), "")

    def test_partitions_of_a_drive(self):
        disk = ("2-1", "2-1_1.0", "host6", "target6_0_0", "6_0_0_0", "block", "sdb")
        self.mk(*disk)
        self.mk(*disk, "sdb1")
        self.mk(*disk, "sdb2")
        self.mk(*disk, "queue")  # not a partition
        self.assertEqual(prompt.block_devices("2-1", self.sys), ["/dev/sdb1", "/dev/sdb2"])

    def test_whole_disk_without_partitions(self):
        self.mk("2-1", "2-1_1.0", "host6", "target6_0_0", "6_0_0_0", "block", "sdc")
        self.assertEqual(prompt.block_devices("2-1", self.sys), ["/dev/sdc"])

    def test_no_drive(self):
        self.mk("2-2", "2-2_1.0")
        self.assertEqual(prompt.block_devices("2-2", self.sys), [])
        self.assertEqual(prompt.block_devices("", self.sys), [])

    def test_allowed_drive_events(self):
        event = ("ACTION=add\nDEVPATH=/devices/pci0000:00/0000:00:14.0/usb2/2-1/2-1:1.0/host6/target6:0:0/"
                 "6:0:0:0/block/sdb/sdb1\nSUBSYSTEM=block\nDEVNAME=/dev/sdb1\nDEVTYPE=partition\nID_BUS=usb\n"
                 "ID_FS_USAGE=filesystem\nID_FS_LABEL=MY_PHOTOS\nID_FS_LABEL_ENC=MY\\x20PHOTOS\nID_VENDOR=SanDisk\n"
                 "ID_MODEL=Ultra_Fit")
        props = prompt.parse_udev(event)
        self.assertTrue(prompt.usb_drive_added(props))
        self.assertEqual(prompt.port_of_devpath(props["DEVPATH"]), "2-1")
        self.assertEqual(prompt.drive_name(props), "MY PHOTOS")
        del props["ID_FS_LABEL"], props["ID_FS_LABEL_ENC"]
        self.assertEqual(prompt.drive_name(props), "SanDisk Ultra Fit")

    def test_not_a_new_usb_filesystem(self):
        base = {"ACTION": "add", "SUBSYSTEM": "block", "DEVNAME": "/dev/sdb1", "ID_BUS": "usb", "ID_FS_USAGE": "filesystem"}
        self.assertFalse(prompt.usb_drive_added({**base, "ACTION": "remove"}))
        self.assertFalse(prompt.usb_drive_added({**base, "ID_BUS": "ata"}))  # internal disk
        self.assertFalse(prompt.usb_drive_added({**base, "ID_FS_USAGE": "raid"}))
        self.assertFalse(prompt.usb_drive_added({**base, "DEVNAME": ""}))

    def test_hub_port_paths(self):
        self.assertEqual(prompt.port_of_devpath("/devices/pci/usb1/1-4/1-4.2/1-4.2:1.0/host7/target7:0:0/7:0:0:0/block/sdd"),
                         "1-4.2")
        self.assertEqual(prompt.port_of_devpath("/devices/virtual/block/loop0"), "")


if __name__ == "__main__":
    unittest.main()
