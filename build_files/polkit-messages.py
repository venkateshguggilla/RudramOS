#!/usr/bin/python3
"""Clearer admin prompts for app installs: say who is asking and exactly what will change.

Flatpak's own prompts only say "Authentication is required to install software". polkit fills
$(name) in a message with the details the caller passes; Flatpak's system helper passes `ref`
and `origin` for installs, `ref` for removals, `remote`, `key` and `path` for the others (see
flatpak-system-helper.c). Only details that are always passed for that action are used, so a
prompt never shows a raw "$(...)". Translated messages of these actions are dropped so every
language shows the new text. The build fails if an action is missing (Flatpak renamed it).
"""
import re
import sys

POLICY = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/polkit-1/actions/org.freedesktop.Flatpak.policy"
WHO = "The App Store (or a terminal)"
MESSAGES = {
    "org.freedesktop.Flatpak.app-install": f"{WHO} wants to install an app for everyone on this PC: $(ref) from $(origin)",
    "org.freedesktop.Flatpak.runtime-install": f"{WHO} wants to install a component that apps need: $(ref) from $(origin)",
    "org.freedesktop.Flatpak.app-uninstall": f"{WHO} wants to remove an app: $(ref)",
    "org.freedesktop.Flatpak.runtime-uninstall": f"{WHO} wants to remove a component that apps used: $(ref)",
    "org.freedesktop.Flatpak.install-bundle": f"{WHO} wants to install an app from the file $(path)",
    "org.freedesktop.Flatpak.configure-remote": f"{WHO} wants to change the app source \"$(remote)\"",
    "org.freedesktop.Flatpak.configure": f"{WHO} wants to change the app store setting \"$(key)\"",
    "org.freedesktop.Flatpak.modify-repo": f"{WHO} wants to change the app store's downloaded data",
}


def rewrite(text: str) -> str:
    for action, message in MESSAGES.items():
        block = re.search(rf'(<action id="{re.escape(action)}">)(.*?)(</action>)', text, re.S)
        if not block:
            raise SystemExit(f"ERROR: {action} not found in {POLICY}")
        body = re.sub(r"\s*<message xml:lang=\"[^\"]*\">.*?</message>", "", block.group(2), flags=re.S)
        body, n = re.subn(r"<message>.*?</message>", f"<message>{message}</message>", body, count=1, flags=re.S)
        if n != 1:
            raise SystemExit(f"ERROR: no message for {action}")
        text = text[:block.start(2)] + body + text[block.end(2):]
    return text


if __name__ == "__main__":
    with open(POLICY, encoding="utf-8") as f:
        original = f.read()
    updated = rewrite(original)
    with open(POLICY, "w", encoding="utf-8") as f:
        f.write(updated)
    for action, message in MESSAGES.items():
        assert message in updated, action
    print(f"Rewrote {len(MESSAGES)} Flatpak prompts in {POLICY}")
