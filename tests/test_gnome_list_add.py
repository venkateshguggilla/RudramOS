"""Tests for build_files/gnome-list-add.py (dock apps and extensions after the base image's own)."""
import importlib.util
import os
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "gnome_list_add", os.path.join(os.path.dirname(__file__), "..", "build_files", "gnome-list-add.py"))
dock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dock)


class DockTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        dock.DISTRO_DB = self.dir

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def test_parse_gvariant_lists(self):
        self.assertEqual(dock.parse_list("['a.desktop', 'b.desktop']"), ["a.desktop", "b.desktop"])
        self.assertEqual(dock.parse_list("@as []"), [])
        with self.assertRaises(ValueError):
            dock.parse_list("[1, 2]")

    def test_base_dock_kept_and_app_appended_once(self):
        self.assertEqual(dock.merged(["org.mozilla.firefox.desktop", "org.gnome.Nautilus.desktop"],
                                     ["io.missioncenter.MissionCenter.desktop"]),
                         ["org.mozilla.firefox.desktop", "org.gnome.Nautilus.desktop", "io.missioncenter.MissionCenter.desktop"])
        self.assertEqual(dock.merged(["io.missioncenter.MissionCenter.desktop"], ["io.missioncenter.MissionCenter.desktop"]),
                         ["io.missioncenter.MissionCenter.desktop"])

    def test_last_dconf_default_wins_and_our_own_file_is_ignored(self):
        self.write("01-base", "[org/gnome/shell]\nfavorite-apps=['old.desktop']\n")
        self.write("04-bluefin", "[org/gnome/desktop/interface]\nx=1\n[org/gnome/shell]\nfavorite-apps=['org.mozilla.firefox.desktop', 'org.gnome.Ptyxis.desktop']\n")
        ours = os.path.join(self.dir, "zz8-rudramos-dock")
        self.write("zz8-rudramos-dock", "[org/gnome/shell]\nfavorite-apps=['stale.desktop']\n")
        self.assertEqual(dock.from_dconf_defaults("favorite-apps", skip=ours), ["org.mozilla.firefox.desktop", "org.gnome.Ptyxis.desktop"])

    def test_no_dconf_default(self):
        self.write("50-other", "[org/gnome/desktop/media-handling]\nautorun-never=true\n")
        self.assertIsNone(dock.from_dconf_defaults("favorite-apps", skip=os.path.join(self.dir, "zz8")))

    def test_keyfile_is_valid_dconf(self):
        text = dock.keyfile("favorite-apps", ["a.desktop", "b.desktop"])
        self.assertIn("[org/gnome/shell]\nfavorite-apps=['a.desktop', 'b.desktop']\n", text)

    def test_other_keys_in_the_same_section_are_separate(self):
        self.write("04-bluefin", "[org/gnome/shell]\nfavorite-apps=['a.desktop']\n"
                                 "enabled-extensions=['logomenu@aryan_k', 'blur-my-shell@aunetx']\n")
        ours = os.path.join(self.dir, "zz8-rudramos-extensions")
        self.assertEqual(dock.from_dconf_defaults("enabled-extensions", skip=ours),
                         ["logomenu@aryan_k", "blur-my-shell@aunetx"])
        self.assertIsNone(dock.from_dconf_defaults("disabled-extensions", skip=ours))
        self.assertIn("enabled-extensions=['x@y']", dock.keyfile("enabled-extensions", ["x@y"]))
