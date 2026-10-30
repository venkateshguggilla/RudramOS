"""Tests for the dual-boot status readers in pcos_control.status (Windows detection, clock).

Run: python -m unittest discover -s tests -p "test_*.py"
"""

import os
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "system_files", "usr", "lib", "pcos-control"))

from pcos_control import status  # noqa: E402


def load_option(description: str) -> bytes:
    """efivarfs file content for a Boot#### variable: attributes + EFI_LOAD_OPTION."""
    path = b"\x04\x04" + b"\x00" * 20  # some device path bytes after the description
    return (struct.pack("<I", 7) + struct.pack("<IH", 1, len(path))
            + description.encode("utf-16-le") + b"\x00\x00" + path)


class DualBootTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.efi = self.dir.name

    def add(self, name, description):
        with open(os.path.join(self.efi, f"{name}-{status.EFI_GLOBAL}"), "wb") as f:
            f.write(load_option(description))

    def test_windows_and_rudramos(self):
        self.add("Boot0000", "Windows Boot Manager")
        self.add("Boot0001", "Fedora")
        self.add("BootOrder", "not a load option")  # other variables are skipped
        with open(os.path.join(self.efi, "Boot0002-00000000-0000-0000-0000-000000000000"), "wb") as f:
            f.write(load_option("Windows Boot Manager"))  # wrong GUID: not a boot entry
        self.assertEqual(status.efi_boot_entries(self.efi), ["Windows Boot Manager", "Fedora"])
        self.assertTrue(status.windows_installed(self.efi))

    def test_no_windows(self):
        self.add("Boot0001", "Fedora")
        self.add("Boot0003", "UEFI: SanDisk USB")
        self.assertFalse(status.windows_installed(self.efi))

    def test_not_uefi_or_unreadable(self):
        self.assertFalse(status.windows_installed(os.path.join(self.efi, "missing")))
        with open(os.path.join(self.efi, f"Boot0004-{status.EFI_GLOBAL}"), "wb") as f:
            f.write(b"\x07\x00")  # truncated
        self.assertEqual(status.efi_boot_entries(self.efi), [])

    def test_local_rtc(self):
        run = lambda out: (lambda *a, **k: SimpleNamespace(stdout=out))  # noqa: E731
        self.assertTrue(status.local_rtc(run("yes\n")))
        self.assertFalse(status.local_rtc(run("no\n")))
        self.assertIsNone(status.local_rtc(run("")))

        def missing(*a, **k):
            raise FileNotFoundError("timedatectl")
        self.assertIsNone(status.local_rtc(missing))


if __name__ == "__main__":
    unittest.main()
