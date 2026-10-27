#!/usr/bin/bash
# RudramOS name and look everywhere people see the system's name: Settings → About, the boot
# menu, the installer, terminal greetings and fastfetch, menus and app grid entries, fallback
# logos and wallpapers. Run by build.sh near the end (needs Pillow, installed for PC Cleaner).
#
# Deliberately unchanged, because tools rely on them: os-release ID / ID_LIKE / VARIANT_ID /
# IMAGE_ID / VERSION_ID (Bluefin's update and ujust tooling, toolbox, akmods), and
# /etc/fedora-release / redhat-release (rpm, dnf and installers read them).
set -euo pipefail

REPO_URL="https://github.com/venkateshguggilla/RudramOS"
GUIDE_URL="${REPO_URL}/blob/main/docs/USER_GUIDE.md"
case "$(cat /usr/share/pcos/gpu-variant 2>/dev/null)" in
nvidia) IMAGE=rudramos-nvidia ;;
nvidia-legacy) IMAGE=rudramos-nvidia-legacy ;;
*) IMAGE=rudramos ;;
esac

### os-release: what Settings → About, the boot menu, the installer and hostnamectl show
OS_RELEASE=/usr/lib/os-release
FEDORA_VERSION=$(sed -n 's/^VERSION_ID=//p' "${OS_RELEASE}" | tr -d '"')
set_field() {
    if grep -q "^$1=" "${OS_RELEASE}"; then
        sed -i "s|^$1=.*|$1=$2|" "${OS_RELEASE}"
    else
        echo "$1=$2" >>"${OS_RELEASE}"
    fi
}
set_field NAME '"RudramOS"'
set_field PRETTY_NAME '"RudramOS"'
set_field VERSION "\"$(date -u +%Y.%m.%d) (based on Fedora ${FEDORA_VERSION})\""
set_field VERSION_CODENAME '"Trishul"'
set_field VARIANT '"RudramOS"'
set_field ANSI_COLOR '"0;38;2;224;38;44"'
set_field DEFAULT_HOSTNAME '"rudramos"'
set_field HOME_URL "\"${REPO_URL}\""
set_field DOCUMENTATION_URL "\"${GUIDE_URL}\""
set_field SUPPORT_URL "\"${REPO_URL}/issues\""
set_field BUG_REPORT_URL "\"${REPO_URL}/issues\""
set_field LOGO 'rudramos-logo'
cat "${OS_RELEASE}"

### Image info (fastfetch's first line, ujust): this image, not Bluefin's
python3 - "${IMAGE}" <<'EOF'
import json, sys
path = "/usr/share/ublue-os/image-info.json"
image = sys.argv[1]
try:
    info = json.load(open(path))
except (OSError, ValueError):
    info = {}
info.update({"image-name": image, "image-vendor": "venkateshguggilla", "image-tag": "latest",
             "image-ref": f"ostree-image-signed:docker://ghcr.io/venkateshguggilla/{image}"})
json.dump(info, open(path, "w"), indent=2)
print(json.dumps(info))
EOF

### Terminal: fastfetch with the trishul and RudramOS colours, without Bluefin's counters
test -s /usr/share/pcos/fastfetch-logo/trishul.txt
python3 - <<'EOF'
import json
src = json.load(open("/usr/share/ublue-os/fastfetch.jsonc"))
drop = ("Murder Chickens", "Bazaar Installs")
mods = []
for m in src.get("modules", []):
    if isinstance(m, dict) and any(d in str(m.get("format", "")) for d in drop):
        continue
    if isinstance(m, dict) and "Forged on" in str(m.get("text", "")):
        m["text"] = m["text"].replace("Forged on", "Installed")
    mods.append(m)
# no two "break"s in a row after removing the counters
clean = [m for i, m in enumerate(mods) if not (m == "break" and i and mods[i - 1] == "break")]
src["modules"] = clean
src.setdefault("display", {}).setdefault("color", {})["keys"] = "38;2;224;38;44"
src["logo"] = {"color": {"1": "38;2;224;38;44", "2": "white"}}
json.dump(src, open("/usr/share/pcos/fastfetch.jsonc", "w"), indent=2, ensure_ascii=False)
json.dump({"fastfetch-config": "/usr/share/pcos/fastfetch.jsonc", "shuffle-logo": True,
           "logo-directory": "/usr/share/pcos/fastfetch-logo"},
          open("/etc/ublue-os/fastfetch.json", "w"), indent=2)
print("fastfetch modules:", len(src["modules"]))
EOF
# Bluefin's terminal greeting (uwelcome, tips about Bluefin) → one line about RudramOS
cat >/etc/profile.d/uwelcome.sh <<'EOF'
# RudramOS: a one-line greeting in interactive terminals (replaces Bluefin's uwelcome).
# Hide it with: touch ~/.config/pcos/no-terminal-greeting
case $- in *i*) ;; *) return 0 2>/dev/null || exit 0 ;; esac
if [ "$(id -u)" != "0" ] && [ -z "${RUDRAMOS_GREETED-}" ] && [ ! -e "${HOME}/.config/pcos/no-terminal-greeting" ]; then
    RUDRAMOS_GREETED=1
    export RUDRAMOS_GREETED
    printf '\033[38;2;224;38;44m🔱 RudramOS\033[0m  Settings: pcos-control · Guide: https://github.com/venkateshguggilla/RudramOS/blob/main/docs/USER_GUIDE.md\n'
fi
EOF

### Menus and the app grid
# Bluefin's documentation entry → the RudramOS user guide
cat >/usr/share/applications/documentation.desktop <<EOF
[Desktop Entry]
Type=Application
Name=RudramOS Guide
GenericName=User Guide
Comment=How to use RudramOS, and what to do when something goes wrong
Exec=xdg-open ${GUIDE_URL}
Icon=rudramos-logo
Terminal=false
Keywords=RudramOS;Help;Docs;Guide;Instructions;
Categories=Utility;
EOF
# Bluefin's community forum isn't ours
sed -i 's/^NoDisplay=.*/NoDisplay=true/' /usr/share/applications/discourse.desktop
# "System Update" opens Control Center → Updates (buttons, admin approval) instead of a terminal
cat >/usr/share/applications/system-update.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=System Update
Comment=Update RudramOS and your apps
Exec=pcos-control --page updates
Icon=software-update-available
Terminal=false
Categories=System;Settings;
Keywords=update;upgrade;rollback;
EOF
# Top-left logo menu: its Documentation item opens the RudramOS guide
LOGOMENU=/usr/share/gnome-shell/extensions/logomenu@aryan_k/extension.js
if [[ -f "${LOGOMENU}" ]]; then
    sed -i "s|https://docs.projectbluefin.io/|${GUIDE_URL}|g" "${LOGOMENU}"
    if grep -q "projectbluefin" "${LOGOMENU}"; then echo "ERROR: logo menu still links to Bluefin" >&2; exit 1; fi
fi

### Fallback logos (old installer screens, boot themes, apps that look for the distro logo)
python3 - <<'EOF'
import glob, os
from PIL import Image
logo = Image.open("/usr/share/icons/hicolor/512x512/apps/rudramos-logo.png").convert("RGBA")
white = Image.new("RGBA", logo.size, (255, 255, 255, 0))
white.putalpha(logo.getchannel("A"))
for path in sorted(glob.glob("/usr/share/pixmaps/fedora*.png") + ["/usr/share/pixmaps/system-logo-white.png"]):
    if not os.path.isfile(path):
        continue
    w, h = Image.open(path).size
    src = white if "white" in os.path.basename(path) else logo
    side = min(w, h)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.alpha_composite(src.resize((side, side), Image.LANCZOS), ((w - side) // 2, (h - side) // 2))
    canvas.save(path)
    print("logo replaced:", path, (w, h))
EOF

### Wallpapers: RudramOS's only, and Bluefin's monthly wallpaper switch off
rm -f /usr/share/gnome-background-properties/*bluefin*.xml /usr/share/gnome-background-properties/f[0-9]*.xml
rm -f /usr/share/ublue-os/user-setup.hooks.d/20-dynamic-wallpaper.sh
mkdir -p /etc/systemd/user
for unit in bluefin-dynamic-wallpaper.timer bluefin-dynamic-wallpaper.service; do
    ln -sf /dev/null "/etc/systemd/user/${unit}"
done
ls /usr/share/gnome-background-properties/
