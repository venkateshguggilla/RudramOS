"""Tests for pcos_control.status (Control Center status readers).

Run: python -m unittest discover -s tests -p "test_*.py"
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "system_files", "usr", "lib", "pcos-control"))

from pcos_control import status  # noqa: E402


def fake_run(outputs):
    """subprocess.run stand-in returning canned stdout per program name."""

    def run(cmd, **_kwargs):
        prog = os.path.basename(cmd[0])
        if prog not in outputs:
            raise FileNotFoundError(prog)
        return SimpleNamespace(stdout=outputs[prog], returncode=0)

    return run


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, name, content):
        path = os.path.join(self.dir.name, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_admin_defaults_to_standard_without_files(self):
        s = status.admin_status(os.path.join(self.dir.name, "none"), os.path.join(self.dir.name, "none2"))
        self.assertEqual(s.mode, "standard")
        self.assertEqual(s.key_counts, {})

    def test_admin_strong_with_key_counts(self):
        mode = self.write("mode", "strong\n")
        maps = self.write("u2f", "venky:KH1,PK1,es256,+presence:KH2,PK2,es256,+presence\nguest:KH3,PK3,es256,+presence\n")
        s = status.admin_status(mode, maps)
        self.assertEqual(s.mode, "strong")
        self.assertEqual(s.key_counts, {"venky": 2, "guest": 1})

    def test_disk_encrypted_tpm_secure_boot(self):
        cmd = self.write("cmdline", "BOOT_IMAGE=/vmlinuz root=UUID=x rd.luks.uuid=luks-abc rhgb quiet\n")
        self.write("tpm/tpm0/tpm_version_major", "2\n")
        s = status.disk_status(cmd, os.path.join(self.dir.name, "tpm"), run=fake_run({"mokutil": "SecureBoot enabled\n"}))
        self.assertTrue(s.encrypted)
        self.assertTrue(s.tpm_present)
        self.assertTrue(s.secure_boot)

    def test_disk_plain_no_tpm_unknown_secure_boot(self):
        cmd = self.write("cmdline", "BOOT_IMAGE=/vmlinuz root=UUID=x rw\n")
        s = status.disk_status(cmd, os.path.join(self.dir.name, "missing"), run=fake_run({}))
        self.assertFalse(s.encrypted)
        self.assertFalse(s.tpm_present)
        self.assertIsNone(s.secure_boot)

    def test_disk_secure_boot_disabled(self):
        cmd = self.write("cmdline", "rd.luks.name=abc=root\n")
        s = status.disk_status(cmd, self.dir.name, run=fake_run({"mokutil": "SecureBoot disabled\n"}))
        self.assertTrue(s.encrypted)
        self.assertFalse(s.secure_boot)

    def test_graphics_needs_driver(self):
        variant = self.write("gpu-variant", "none\n")
        run = fake_run({"pcos-gpu-detect": "rudramos-nvidia-legacy\tNVIDIA GP107 [GeForce GTX 1050 Ti]\tNVIDIA Pascal\n"})
        s = status.graphics_status("/x/pcos-gpu-detect", variant, run=run)
        self.assertEqual(s.installed, "rudramos")
        self.assertEqual(s.wanted, "rudramos-nvidia-legacy")
        self.assertIn("1050 Ti", s.gpu_name)

    def test_graphics_detection_failure_keeps_installed(self):
        variant = self.write("gpu-variant", "nvidia\n")
        s = status.graphics_status("/x/pcos-gpu-detect", variant, run=fake_run({}))
        self.assertEqual(s.installed, "rudramos-nvidia")
        self.assertEqual(s.wanted, "rudramos-nvidia")

    def test_system_booted_and_staged(self):
        osr = self.write("os-release", 'NAME="Bluefin"\nPRETTY_NAME="RudramOS"\n')
        date = self.write("build-date", "20261018\n")
        rpm = json.dumps({"deployments": [
            {"booted": False, "staged": True, "container-image-reference": "ostree-image-signed:docker://ghcr.io/o/rudramos-nvidia:latest"},
            {"booted": True, "staged": False, "container-image-reference": "ostree-image-signed:docker://ghcr.io/o/pcos:latest"},
        ]})
        s = status.system_status(osr, date, run=fake_run({"rpm-ostree": rpm}))
        self.assertEqual(s.name, "RudramOS")
        self.assertEqual(s.build_date, "20261018")
        self.assertEqual(s.booted_image, "pcos:latest")  # a PC not switched over to the new name yet
        self.assertEqual(s.staged_image, "rudramos-nvidia:latest")

    def test_system_without_rpm_ostree(self):
        s = status.system_status(os.path.join(self.dir.name, "no"), os.path.join(self.dir.name, "no2"), run=fake_run({}))
        self.assertEqual(s.name, "RudramOS")
        self.assertEqual(s.booted_image, "")
        self.assertEqual(s.staged_image, "")

    def test_apps_on_with_extensions(self):
        ext = self.write("ext.json", json.dumps({
            "{446900e4-71c2-419f-a6a7-df9c091e268b}": {"name": "Bitwarden", "install_url": "https://x"},
            "example@ext.test": {"name": ""},
        }))
        s = status.apps_status(ext, run=fake_run({"systemctl": "active\n"}))
        self.assertTrue(s.approval_on)
        self.assertEqual(s.extensions["{446900e4-71c2-419f-a6a7-df9c091e268b}"], "Bitwarden")
        self.assertEqual(s.extensions["example@ext.test"], "example@ext.test")

    def test_apps_off_and_bad_json(self):
        ext = self.write("ext.json", "not json")
        s = status.apps_status(ext, run=fake_run({"systemctl": "inactive\n"}))
        self.assertFalse(s.approval_on)
        self.assertEqual(s.extensions, {})

    def test_apps_unknown_without_systemctl(self):
        s = status.apps_status(os.path.join(self.dir.name, "missing.json"), run=fake_run({}))
        self.assertIsNone(s.approval_on)

    def test_network_trust_and_sharing(self):
        trusted = self.write("trusted", "bbbb-2222\tWired connection 1\n")
        nm = ("aaaa-1111:802-11-wireless:wlp2s0:Cafe\\: Free WiFi\n"
              "bbbb-2222:802-3-ethernet:enp3s0:Wired connection 1\n"
              "cccc-3333:vpn:tun0:Work VPN\n"
              "dddd-4444:802-11-wireless::Saved but inactive\n")
        s = status.network_status(trusted, run=fake_run({"nmcli": nm, "firewall-cmd": "dhcpv6-client kdeconnect ssh\n"}))
        self.assertEqual([(n.name, n.device, n.trusted) for n in s.networks],
                         [("Cafe: Free WiFi", "wlp2s0", False), ("Wired connection 1", "enp3s0", True)])
        self.assertEqual(s.shared, {"phone", "ssh"})

    def test_network_without_tools(self):
        s = status.network_status(os.path.join(self.dir.name, "none"), run=fake_run({}))
        self.assertEqual(s.networks, [])
        self.assertEqual(s.shared, set())

    def test_usb_pending_devices(self):
        mode = self.write("usb-mode", "allow-input\n")
        self.write("pending/9", 'block id 1b4f:9206 name "Flash Disk" with-interface { 08:06:50 03:01:01 }\n')
        self.write("pending/7", 'block id 0781:5581 name "Ultra" with-interface 08:06:50\n')
        self.write("pending/7.tmp", "partial write, ignored\n")
        outputs = {"pcos-usb-describe": "Storage\tUltra\tok\tAllow it if it's yours.\n"}
        s = status.usb_status(mode, os.path.join(self.dir.name, "pending"), "/x/pcos-usb-describe", run=fake_run(outputs))
        self.assertEqual(s.mode, "allow-input")
        self.assertEqual([d.id for d in s.pending], ["7", "9"])
        self.assertEqual((s.pending[0].kind, s.pending[0].name, s.pending[0].level), ("Storage", "Ultra", "ok"))

    def test_usb_defaults_without_files(self):
        s = status.usb_status(os.path.join(self.dir.name, "no"), os.path.join(self.dir.name, "no-dir"), run=fake_run({}))
        self.assertEqual(s.mode, "ask")
        self.assertEqual(s.pending, [])

    def test_privacy_from_conf(self):
        conf = self.write("privacy.conf", "# managed\npreset=custom\ndns=mullvad\ntrackers=on\njournal_days=3\nbogus=1\n")
        rules = self.write("killswitch.nft", "table inet pcos_killswitch {}\n")
        s = status.privacy_status(conf, rules)
        self.assertEqual(s.settings["preset"], "custom")
        self.assertEqual(s.settings["dns"], "mullvad")
        self.assertEqual(s.settings["trackers"], "on")
        self.assertEqual(s.settings["dot"], "opportunistic")  # default kept
        self.assertNotIn("bogus", s.settings)
        self.assertTrue(s.killswitch_on)

    def test_privacy_defaults(self):
        s = status.privacy_status(os.path.join(self.dir.name, "no"), os.path.join(self.dir.name, "no.nft"))
        self.assertEqual(s.settings, status.PRIVACY_DEFAULTS)
        self.assertFalse(s.killswitch_on)

    def test_timeout_is_handled(self):
        def slow(*_a, **_k):
            raise subprocess.TimeoutExpired("rpm-ostree", 30)

        s = status.system_status(os.path.join(self.dir.name, "no"), os.path.join(self.dir.name, "no2"), run=slow)
        self.assertEqual(s.staged_image, "")


if __name__ == "__main__":
    unittest.main()


def update_run(deployments, digest=None, timer="Wed 2026-10-21 04:00:00 IST"):
    """fake run for update_status: rpm-ostree deployments, skopeo digest (None = offline), timer."""
    outputs = {"rpm-ostree": json.dumps({"deployments": deployments}), "systemctl": timer}
    if digest is not None:
        outputs["skopeo"] = digest + "\n"
    return fake_run(outputs)


def dep(digest, booted=False, staged=False, version="44.20261020.0", ts=1792500000, name="rudramos"):
    return {"booted": booted, "staged": staged, "version": version, "timestamp": ts,
            "container-image-reference": f"ostree-image-signed:docker://ghcr.io/o/{name}:latest",
            "container-image-reference-digest": digest}


class UpdateStatusTests(unittest.TestCase):
    def test_up_to_date(self):
        s = status.update_status(run=update_run([dep("sha256:aaa", booted=True), dep("sha256:old", version="44.20261019.0")], "sha256:aaa"))
        self.assertEqual(s.state, "current")
        self.assertEqual(s.booted.version, "44.20261020.0")
        self.assertEqual(s.booted.ref, "ghcr.io/o/rudramos:latest")
        self.assertEqual(s.rollback.version, "44.20261019.0")
        self.assertIsNone(s.staged)
        self.assertEqual(s.next_automatic, "Wed 2026-10-21 04:00:00 IST")

    def test_newer_image_online(self):
        s = status.update_status(run=update_run([dep("sha256:aaa", booted=True)], "sha256:bbb"))
        self.assertEqual(s.state, "available")
        self.assertEqual(s.remote_digest, "sha256:bbb")

    def test_downloaded_and_waiting_for_restart(self):
        s = status.update_status(run=update_run([dep("sha256:bbb", staged=True), dep("sha256:aaa", booted=True)], "sha256:bbb"))
        self.assertEqual(s.state, "ready")
        self.assertEqual(s.staged.digest, "sha256:bbb")
        self.assertIsNone(s.rollback)  # the staged one isn't "previous"

    def test_even_newer_than_the_downloaded_update(self):
        s = status.update_status(run=update_run([dep("sha256:bbb", staged=True), dep("sha256:aaa", booted=True)], "sha256:ccc"))
        self.assertEqual(s.state, "available")

    def test_offline_is_unknown_but_a_downloaded_update_still_shows(self):
        offline = status.update_status(run=update_run([dep("sha256:aaa", booted=True)], digest=None))
        self.assertEqual(offline.state, "unknown")
        ready = status.update_status(run=update_run([dep("sha256:bbb", staged=True), dep("sha256:aaa", booted=True)], digest=None))
        self.assertEqual(ready.state, "ready")

    def test_not_checking_online_does_not_call_skopeo(self):
        def run(cmd, **kw):
            self.assertNotEqual(os.path.basename(cmd[0]), "skopeo")
            return update_run([dep("sha256:aaa", booted=True)])(cmd, **kw)
        self.assertEqual(status.update_status(check_online=False, run=run).state, "unknown")

    def test_boot_menu_theme_flag(self):
        d = tempfile.mkdtemp()
        flag = os.path.join(d, "no-grub-theme")
        self.assertTrue(status.boot_menu_theme_on(flag))
        open(flag, "w").close()
        self.assertFalse(status.boot_menu_theme_on(flag))

    def test_earlier_online_result_is_reused_without_checking_again(self):
        s = status.update_status(check_online=False, known_remote="sha256:bbb",
                                 run=update_run([dep("sha256:aaa", booted=True)]))
        self.assertEqual(s.state, "available")


class OperationTests(unittest.TestCase):
    """Detecting a running driver install / update from a fake /proc."""

    def setUp(self):
        self.proc = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.proc, ignore_errors=True))
        with open(os.path.join(self.proc, "stat"), "w") as f:
            f.write("cpu  1 2 3\nbtime 1792500000\n")

    def add(self, pid, argv, start_ticks=6000):
        d = os.path.join(self.proc, str(pid))
        os.makedirs(d)
        with open(os.path.join(d, "cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in argv) + b"\0")
        fields = ["S"] + ["0"] * 18 + [str(start_ticks)] + ["0"] * 10
        with open(os.path.join(d, "stat"), "w") as f:
            f.write(f"{pid} (some (name)) " + " ".join(fields))

    def test_nothing_running(self):
        self.add(1, ["/usr/lib/systemd/systemd"])
        self.assertIsNone(status.system_operation(self.proc))

    def test_driver_install_wins_over_its_bootc_child(self):
        self.add(4242, ["/usr/bin/bootc", "switch", "--enforce-container-sigpolicy", "ghcr.io/o/rudramos-nvidia-legacy:latest"])
        self.add(4200, ["/bin/bash", "/usr/libexec/pcos/pcos-gpu-switch", "rudramos-nvidia-legacy"], start_ticks=5000)
        op = status.system_operation(self.proc)
        self.assertEqual(op.kind, "driver")
        ticks = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self.assertAlmostEqual(op.started, 1792500000 + 5000 / ticks)

    def test_update_and_rollback(self):
        self.add(10, ["/bin/bash", "/usr/libexec/pcos/pcos-update", "upgrade"])
        self.assertEqual(status.system_operation(self.proc).kind, "update")
        self.add(11, ["/bin/bash", "/usr/libexec/pcos/pcos-update", "rollback"], start_ticks=1)
        self.assertEqual(status.system_operation(self.proc).kind, "rollback")  # the earlier one

    def test_bootc_from_a_terminal(self):
        self.add(20, ["bootc", "upgrade"])
        self.assertEqual(status.system_operation(self.proc).kind, "update")
