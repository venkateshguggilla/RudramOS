#!/usr/bin/python3
"""Pins RudramOS apps to the dock, after the base image's own dock apps.

GNOME keeps the dock in org.gnome.shell favorite-apps, a single list, so adding apps means
writing the whole list. To keep Bluefin's choices, this reads the list the image would use
(a dconf default in /etc/dconf/db/distro.d, else the gschema default) and writes it back with
our apps added, as a dconf default users can still change (right-click > Pin / Unpin).

Usage: dock-favorites.py OUTPUT_KEYFILE APP.desktop...
"""
import ast
import glob
import os
import re
import subprocess
import sys

DISTRO_DB = "/etc/dconf/db/distro.d"


def parse_list(text: str) -> list[str]:
    """A GVariant string array ("['a.desktop', 'b.desktop']" or "@as []") -> list."""
    text = text.strip()
    if text.startswith("@as"):
        text = text[3:].strip()
    value = ast.literal_eval(text)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"not a string list: {text}")
    return value


def from_dconf_defaults(skip: str) -> list[str] | None:
    """favorite-apps from the base image's dconf defaults (the last file that sets it wins)."""
    found = None
    for path in sorted(glob.glob(os.path.join(DISTRO_DB, "*"))):
        if os.path.abspath(path) == os.path.abspath(skip) or not os.path.isfile(path):
            continue
        section = None
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1].strip("/")
                elif section == "org/gnome/shell" and re.match(r"favorite-apps\s*=", line):
                    found = parse_list(line.split("=", 1)[1])
    return found


def from_gschema() -> list[str]:
    """The compiled schema default (includes the base image's .gschema.override files)."""
    out = subprocess.run(["gsettings", "get", "org.gnome.shell", "favorite-apps"],
                         env={**os.environ, "GSETTINGS_BACKEND": "memory"},
                         capture_output=True, text=True, check=True).stdout
    return parse_list(out)


def merged(base: list[str], add: list[str]) -> list[str]:
    return base + [a for a in add if a not in base]


def keyfile(apps: list[str]) -> str:
    items = ", ".join(f"'{a}'" for a in apps)
    return ("# RudramOS dock: the base image's dock apps plus RudramOS ones (build_files/dock-favorites.py).\n"
            "# A default only: right-click an app in the dock to pin or unpin it.\n"
            f"[org/gnome/shell]\nfavorite-apps=[{items}]\n")


if __name__ == "__main__":
    output, add = sys.argv[1], sys.argv[2:]
    base = from_dconf_defaults(skip=output)
    source = "dconf defaults"
    if base is None:
        base, source = from_gschema(), "gschema default"
    apps = merged(base, add)
    with open(output, "w", encoding="utf-8") as f:
        f.write(keyfile(apps))
    print(f"Dock ({source}): {base} + {add} -> {apps}")
