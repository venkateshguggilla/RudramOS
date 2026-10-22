#!/usr/bin/python3
"""Adds items to a GNOME Shell list setting, after the base image's own items.

GNOME keeps the dock (favorite-apps) and the switched-on extensions (enabled-extensions) in
org.gnome.shell as single lists, so adding to them means writing the whole list. To keep
Bluefin's choices, this reads the list the image would use (a dconf default in
/etc/dconf/db/distro.d, else the gschema default) and writes it back with our items added, as a
dconf default users can still change.

Usage: gnome-list-add.py OUTPUT_KEYFILE KEY ITEM...
       e.g. gnome-list-add.py /etc/dconf/db/distro.d/zz8-rudramos-dock favorite-apps app.desktop
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


def from_dconf_defaults(key: str, skip: str) -> list[str] | None:
    """The key from the base image's dconf defaults (the last file that sets it wins)."""
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
                elif section == "org/gnome/shell" and re.match(rf"{re.escape(key)}\s*=", line):
                    found = parse_list(line.split("=", 1)[1])
    return found


def from_gschema(key: str) -> list[str]:
    """The compiled schema default (includes the base image's .gschema.override files)."""
    out = subprocess.run(["gsettings", "get", "org.gnome.shell", key],
                         env={**os.environ, "GSETTINGS_BACKEND": "memory"},
                         capture_output=True, text=True, check=True).stdout
    return parse_list(out)


def merged(base: list[str], add: list[str]) -> list[str]:
    return base + [a for a in add if a not in base]


def keyfile(key: str, items: list[str]) -> str:
    values = ", ".join(f"'{a}'" for a in items)
    return (f"# RudramOS: the base image's {key} plus RudramOS ones (build_files/gnome-list-add.py).\n"
            "# A default only: users can still change it.\n"
            f"[org/gnome/shell]\n{key}=[{values}]\n")


if __name__ == "__main__":
    output, key, add = sys.argv[1], sys.argv[2], sys.argv[3:]
    base = from_dconf_defaults(key, skip=output)
    source = "dconf defaults"
    if base is None:
        base, source = from_gschema(key), "gschema default"
    items = merged(base, add)
    with open(output, "w", encoding="utf-8") as f:
        f.write(keyfile(key, items))
    print(f"{key} ({source}): {base} + {add} -> {items}")
