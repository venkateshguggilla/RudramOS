"""Tests for pcos_control.firstboot (first-boot setup logic).

Run: python -m unittest discover -s tests -p "test_*.py"
"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "system_files", "usr", "lib", "pcos-control"))

from pcos_control import firstboot  # noqa: E402


def ctx(**kw):
    base = dict(encrypted=True, nvidia=False, driver_needed=False, mok="not-needed", networks=1, phone_link=True)
    base.update(kw)
    return firstboot.Context(**base)


class StepTests(unittest.TestCase):
    def test_typical_pc(self):
        self.assertEqual(firstboot.steps(ctx()),
                         ["welcome", "admin", "disk", "privacy", "network", "phone", "protect", "done"])

    def test_no_network_no_phone_link(self):
        steps = firstboot.steps(ctx(networks=0, phone_link=False))
        self.assertNotIn("network", steps)
        self.assertNotIn("phone", steps)

    def test_graphics_only_when_something_to_do(self):
        self.assertNotIn("graphics", firstboot.steps(ctx(nvidia=True, mok="enrolled")))
        self.assertIn("graphics", firstboot.steps(ctx(driver_needed=True)))
        self.assertIn("graphics", firstboot.steps(ctx(nvidia=True, mok="missing")))
        self.assertIn("graphics", firstboot.steps(ctx(nvidia=True, mok="pending")))

    def test_always_starts_and_ends_the_same(self):
        for c in (ctx(), ctx(networks=0, phone_link=False, encrypted=False)):
            s = firstboot.steps(c)
            self.assertEqual(s[:4], ["welcome", "admin", "disk", "privacy"])
            self.assertEqual(s[-2:], ["protect", "done"])


class MokTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.key = os.path.join(self.dir.name, "key.der")
        open(self.key, "w").close()
        self.flag = os.path.join(self.dir.name, "pending")

    def state(self, out, sb=True):
        run = lambda *a, **k: SimpleNamespace(stdout=out, stderr="")  # noqa: E731
        return firstboot.mok_state(sb, self.key, self.flag, run)

    def test_states(self):
        self.assertEqual(self.state(f"{self.key} is already enrolled\n"), "enrolled")
        self.assertEqual(self.state(f"{self.key} is not enrolled\n"), "missing")
        self.assertEqual(self.state(f"{self.key} is already in the enrollment request\n"), "pending")
        self.assertEqual(self.state("something odd"), "not-needed")

    def test_secure_boot_off_or_unknown(self):
        self.assertEqual(self.state("is not enrolled", sb=False), "not-needed")
        self.assertEqual(self.state("is not enrolled", sb=None), "not-needed")

    def test_no_key_in_this_image(self):
        os.remove(self.key)
        self.assertEqual(self.state("is not enrolled"), "not-needed")

    def test_pending_flag_wins(self):
        open(self.flag, "w").close()
        self.assertEqual(self.state("is not enrolled"), "pending")

    def test_mokutil_missing(self):
        def run(*a, **k):
            raise FileNotFoundError("mokutil")
        self.assertEqual(firstboot.mok_state(True, self.key, self.flag, run), "not-needed")


class StartTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.home = self.dir.name

    def test_runs_once_for_admins(self):
        self.assertTrue(firstboot.should_start(self.home, admin=True))
        self.assertFalse(firstboot.should_start(self.home, admin=False))
        firstboot.mark_done(self.home)
        self.assertTrue(firstboot.is_done(self.home))
        self.assertFalse(firstboot.should_start(self.home, admin=True))

    def test_older_setup_version_runs_again(self):
        os.makedirs(os.path.join(self.home, "pcos"))
        with open(firstboot.marker(self.home), "w") as f:
            f.write("0\n")
        self.assertTrue(firstboot.should_start(self.home, admin=True))

    def test_initial_setup_detection(self):
        proc = os.path.join(self.dir.name, "proc")
        for pid, comm in (("1", "systemd"), ("42", "gnome-initial-s"), ("self", "x")):
            os.makedirs(os.path.join(proc, pid))
            with open(os.path.join(proc, pid, "comm"), "w") as f:
                f.write(comm + "\n")
        self.assertTrue(firstboot.initial_setup_running(proc))
        os.remove(os.path.join(proc, "42", "comm"))
        self.assertFalse(firstboot.initial_setup_running(proc))
        self.assertFalse(firstboot.initial_setup_running(os.path.join(self.dir.name, "missing")))


if __name__ == "__main__":
    unittest.main()
