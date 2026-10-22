#!/bin/bash
# RudramOS image build script. Runs inside the Containerfile build (see Containerfile).

set -ouex pipefail

GPU="${GPU:-none}"
REGISTRY="ghcr.io/venkateshguggilla"
# All image variants: a PC may switch between them, so each must be signature-checked
# New names, and the names before the rename to RudramOS (still published during the switch-over)
IMAGE_REPOS=("${REGISTRY}/rudramos" "${REGISTRY}/rudramos-nvidia" "${REGISTRY}/rudramos-nvidia-legacy"
    "${REGISTRY}/pcos" "${REGISTRY}/pcos-nvidia" "${REGISTRY}/pcos-nvidia-legacy")
SIGNING_PUBKEY="/etc/pki/containers/pcos.pub"

### System files
# Copy the contents of system_files/ in the git repo to /
cp -avf "/ctx/system_files"/. /
chmod 0755 /usr/bin/pcos-privacy /usr/bin/pcos-killswitch /usr/bin/pcos-usb /usr/libexec/pcos/pcos-usb-describe /usr/libexec/pcos/pcos-usb-watch /usr/libexec/pcos/pcos-usb-prompt /usr/libexec/pcos/pcos-usb-firstboot /usr/bin/pcos-network /usr/libexec/pcos/pcos-network-prompt /usr/lib/NetworkManager/dispatcher.d/50-pcos-network-trust /usr/bin/pcos-app-guard /usr/bin/pcos-browser-extensions /usr/libexec/pcos/pcos-app-guard-notify /usr/bin/pcos-control /usr/libexec/pcos/pcos-terminal-run /usr/bin/pcos-admin-mode /usr/bin/pcos-disk-security /usr/bin/pcos-driver-assistant /usr/libexec/pcos/pcos-gpu-detect /usr/libexec/pcos/pcos-gpu-switch

### Branding (Phase 1 basics; full branding in Phase 12)
sed -i 's/^PRETTY_NAME=.*/PRETTY_NAME="RudramOS"/' /usr/lib/os-release
mkdir -p /usr/share/pcos
date -u +%Y%m%d > /usr/share/pcos/build-date

### Look and feel (images made by tools/make-branding.py): trishul logo, wallpapers, red accent,
# dark style, login screen logo, boot menu theme. The dconf defaults are compiled by the
# "dconf update" further down.
if grep -q '^LOGO=' /usr/lib/os-release; then
    sed -i 's/^LOGO=.*/LOGO=rudramos-logo/' /usr/lib/os-release
else
    echo 'LOGO=rudramos-logo' >>/usr/lib/os-release
fi
# Login screen (GDM) reads /etc/dconf/db/gdm.d through its own dconf profile
if [[ ! -f /usr/share/dconf/profile/gdm && ! -f /etc/dconf/profile/gdm ]]; then
    printf 'user-db:user\nsystem-db:gdm\nfile-db:/usr/share/gdm/greeter-dconf-defaults\n' >/etc/dconf/profile/gdm
fi
# Boot menu: GRUB needs its own font next to the theme; .stamp lets the installer skip unchanged themes
GRUB_THEME=/usr/share/pcos/grub/rudramos
for font in /usr/share/grub/unicode.pf2 /usr/share/grub2/unicode.pf2; do
    [[ -f "${font}" ]] && cp "${font}" "${GRUB_THEME}/unicode.pf2" && break
done
[[ -f "${GRUB_THEME}/unicode.pf2" ]] || { echo "ERROR: no GRUB unicode.pf2 font for the boot menu theme" >&2; exit 1; }
(cd "${GRUB_THEME}" && find . -type f ! -name .stamp -print0 | sort -z | xargs -0 sha256sum | sha256sum >.stamp)
chmod 0755 /usr/libexec/pcos/pcos-grub-theme /usr/libexec/pcos/pcos-image-rename /usr/libexec/pcos/pcos-update /usr/libexec/pcos/pcos-app-store
systemctl enable pcos-grub-theme.service
# Dock: the base image's apps plus Mission Center (task manager: running apps and processes,
# End task, CPU/GPU/memory/disk use). Preinstalled from Flathub like Bazaar.
python3 /ctx/gnome-list-add.py /etc/dconf/db/distro.d/zz8-rudramos-dock favorite-apps io.missioncenter.MissionCenter.desktop
# After the rename from pcos: move installed PCs to the rudramos image names once those are available
systemctl enable pcos-image-rename.timer

### Boot animation (Plymouth): Shiva's eyes and the trishul, with the disk password prompt.
# Set before gpu.sh so an initramfs rebuilt there (nvidia-legacy) already has it.
dnf5 install -y plymouth-plugin-script
plymouth-set-default-theme rudramos

### GPU drivers for this image variant
/ctx/gpu.sh

### Initramfs with the boot animation. nvidia-legacy already rebuilt it in gpu.sh; the other
# variants come with the base image's, so rebuild it the same way, keeping any NVIDIA modules.
KERNEL="$(rpm -q kernel --queryformat '%{VERSION}-%{RELEASE}.%{ARCH}\n' | tail -n1)"
INITRAMFS="/lib/modules/${KERNEL}/initramfs.img"
if [[ "${GPU}" != "nvidia-legacy" ]]; then
    lsinitrd "${INITRAMFS}" >/tmp/initramfs-before.txt
    export DRACUT_NO_XATTR=1
    dracut --no-hostonly --kver "${KERNEL}" --reproducible --add ostree -f "${INITRAMFS}"
    chmod 0600 "${INITRAMFS}"
    if grep -qE "nvidia(-drm)?\.ko" /tmp/initramfs-before.txt; then
        lsinitrd "${INITRAMFS}" >/tmp/initramfs-after.txt
        grep -qE "nvidia(-drm)?\.ko" /tmp/initramfs-after.txt || { echo "ERROR: NVIDIA modules lost from initramfs" >&2; exit 1; }
    fi
fi
lsinitrd "${INITRAMFS}" >/tmp/initramfs.txt
grep -q "plymouth/themes/rudramos/frame-39.png" /tmp/initramfs.txt || { echo "ERROR: boot animation missing from initramfs" >&2; exit 1; }
grep -q "plymouth/script.so" /tmp/initramfs.txt || { echo "ERROR: Plymouth script plugin missing from initramfs" >&2; exit 1; }

### Only accept RudramOS images signed with our cosign key
# The public key must be committed as keys/cosign.pub. Fail the build without it,
# otherwise the policy below would point at a missing key and block all updates.
if [[ ! -s /ctx/keys/cosign.pub ]]; then
    echo "ERROR: keys/cosign.pub is missing. Generate it with: cosign generate-key-pair" >&2
    exit 1
fi
install -Dm644 /ctx/keys/cosign.pub "${SIGNING_PUBKEY}"

command -v jq >/dev/null || dnf5 install -y jq
POLICY=/etc/containers/policy.json
mkdir -p /etc/containers/registries.d
echo "docker:" > /etc/containers/registries.d/pcos.yaml
for repo in "${IMAGE_REPOS[@]}"; do
    jq --arg repo "${repo}" --arg key "${SIGNING_PUBKEY}" \
        '.transports.docker[$repo] = [{
            "type": "sigstoreSigned",
            "keyPath": $key,
            "signedIdentity": {"type": "matchRepository"}
        }]' "${POLICY}" > /tmp/policy.json
    install -m644 /tmp/policy.json "${POLICY}"
    printf '  %s:\n    use-sigstore-attachments: true\n' "${repo}" >> /etc/containers/registries.d/pcos.yaml
done

### Packages
# pam-u2f/pamu2fcfg: FIDO2 security keys for Strong admin mode; pamtester: test before enabling it
dnf5 install -y pam-u2f pamu2fcfg pamtester
# Control Center (GTK4 + libadwaita, Python)
dnf5 install -y python3-gobject gtk4 libadwaita

### Admin approval modes (docs/DESIGN.md §4.3)
# sudo and polkit (all desktop admin prompts) authenticate through /etc/pam.d/pcos-admin,
# which pcos-admin-mode switches between the Standard and Strong templates.
for service in sudo polkit-1; do
    # Fedora ships some PAM files only in the vendor dir; a copy in /etc/pam.d takes priority
    if [[ ! -e "/etc/pam.d/${service}" && -e "/usr/lib/pam.d/${service}" ]]; then
        cp -a "/usr/lib/pam.d/${service}" "/etc/pam.d/${service}"
    fi
    sed -i -E 's/^auth([[:space:]]+)include([[:space:]]+)system-auth[[:space:]]*$/auth\1include\2pcos-admin/' "/etc/pam.d/${service}"
    if ! grep -qE '^auth[[:space:]]+include[[:space:]]+pcos-admin' "/etc/pam.d/${service}" ||
        grep -qE '^auth[[:space:]]+include[[:space:]]+system-auth' "/etc/pam.d/${service}"; then
        echo "ERROR: could not route /etc/pam.d/${service} auth through pcos-admin:" >&2
        cat "/etc/pam.d/${service}" >&2
        exit 1
    fi
done
install -m 0644 -o root -g root /dev/null /etc/u2f_mappings
mkdir -p /etc/pcos
echo standard > /etc/pcos/admin-mode

### App approval (Gatekeeper-style) with fapolicyd (docs/DESIGN.md §4.4)
# Only programs in Downloads, Desktop, on USB drives and user-level Flatpaks need approval;
# fapolicyd's strict Fedora default rules are replaced by RudramOS rules.
dnf5 install -y fapolicyd
rm -f /etc/fapolicyd/rules.d/*.rules
install -m 0644 /usr/share/pcos/fapolicyd/10-pcos-base.rules /usr/share/pcos/fapolicyd/90-pcos-final.rules /etc/fapolicyd/rules.d/
FAPOLICYD_CONF=/etc/fapolicyd/fapolicyd.conf
sed -i -E 's/^trust[[:space:]]*=.*/trust = file/; s/^integrity[[:space:]]*=.*/integrity = sha256/' "${FAPOLICYD_CONF}"
sed -i -E 's/^watch_fs[[:space:]]*=.*/watch_fs = ext2,ext3,ext4,tmpfs,xfs,vfat,iso9660,btrfs,exfat,ntfs3/' "${FAPOLICYD_CONF}"
grep -qx 'trust = file' "${FAPOLICYD_CONF}" && grep -qx 'integrity = sha256' "${FAPOLICYD_CONF}" ||
    { echo "ERROR: could not configure ${FAPOLICYD_CONF}" >&2; cat "${FAPOLICYD_CONF}" >&2; exit 1; }
mkdir -p /etc/fapolicyd/trust.d
touch /etc/fapolicyd/trust.d/pcos-approved
systemctl enable fapolicyd.service pcos-app-guard-rules.service

### Browser extension control (docs/DESIGN.md §4.5)
systemctl enable pcos-firefox-policy.service

### Network protection (docs/DESIGN.md §5)
# Every network starts in pcos-public (all incoming blocked, stealth); pcos-network and the
# NetworkManager hook move admin-approved Home networks to pcos-home.
FIREWALLD_CONF=/etc/firewalld/firewalld.conf
sed -i -E 's/^DefaultZone=.*/DefaultZone=pcos-public/' "${FIREWALLD_CONF}"
grep -qx 'DefaultZone=pcos-public' "${FIREWALLD_CONF}" || { echo "ERROR: could not set the default firewall zone" >&2; exit 1; }
firewall-offline-cmd --check-config
systemctl enable firewalld.service
mkdir -p /etc/pcos
touch /etc/pcos/trusted-networks
# Nothing listening or announcing by default: no SSH server, no printer auto-adding over the
# network (cups-browsed, CVE-2024-47176 class), Avahi browses but never announces this PC
systemctl disable sshd.service 2>/dev/null || true
systemctl mask cups-browsed.service
AVAHI_CONF=/etc/avahi/avahi-daemon.conf
if [[ -f "${AVAHI_CONF}" ]]; then
    sed -i -E 's/^#?[[:space:]]*disable-publishing[[:space:]]*=.*/disable-publishing=yes/' "${AVAHI_CONF}"
    grep -qx 'disable-publishing=yes' "${AVAHI_CONF}" || { echo "ERROR: could not configure ${AVAHI_CONF}" >&2; exit 1; }
fi

### USB device approval with USBGuard (docs/DESIGN.md §6)
# New USB devices are blocked until approved; devices connected at first boot are trusted
# (pcos-usb-firstboot). Only root may talk to the daemon: approvals go through pcos-usb + polkit.
# usbguard-dbus is deliberately not installed (GNOME would auto-allow devices on unlock).
dnf5 install -y usbguard
USBGUARD_CONF=/etc/usbguard/usbguard-daemon.conf
for setting in ImplicitPolicyTarget=block PresentDevicePolicy=apply-policy PresentControllerPolicy=keep \
    InsertedDevicePolicy=apply-policy IPCAllowedUsers=root IPCAllowedGroups= RuleFolder=/etc/usbguard/rules.d/; do
    key="${setting%%=*}"
    if grep -qE "^#?${key}=" "${USBGUARD_CONF}"; then
        sed -i -E "s|^#?${key}=.*|${setting}|" "${USBGUARD_CONF}"
    else
        echo "${setting}" >>"${USBGUARD_CONF}"
    fi
    grep -qxF "${setting}" "${USBGUARD_CONF}" || { echo "ERROR: could not set ${setting} in ${USBGUARD_CONF}" >&2; exit 1; }
done
mkdir -p /etc/usbguard/rules.d
chmod 0700 /etc/usbguard/rules.d
: >/etc/usbguard/rules.conf
chmod 0600 /etc/usbguard/rules.conf
echo ask >/etc/pcos/usb-mode
systemctl enable usbguard.service pcos-usb-firstboot.service pcos-usb-watch.service
# GNOME defaults: no autorun, don't open new drives automatically, GNOME's own USB protection off
dconf update

### Privacy (docs/DESIGN.md §7)
# No weekly "count me" ping to Fedora
systemctl mask rpm-ostree-countme.timer rpm-ostree-countme.service
# Time from NTS servers (authenticated + encrypted) instead of plain NTP pools
CHRONY_CONF=/etc/chrony.conf
if [[ -f "${CHRONY_CONF}" ]]; then
    sed -i -E 's/^(pool|server|sourcedir)[[:space:]]/#&/' "${CHRONY_CONF}"
    cat >>"${CHRONY_CONF}" <<'EOF'

# RudramOS: authenticated, encrypted time (NTS) instead of plain NTP pools
server time.cloudflare.com iburst nts
server nts.netnod.se iburst nts
server ptbtime1.ptb.de iburst nts
ntsdumpdir /var/lib/chrony
EOF
fi
# Balanced preset by default: MAC randomization, encrypted DNS (Quad9), short log retention
mkdir -p /etc/pcos/firefox-policies.d
PCOS_NO_RELOAD=1 /usr/bin/pcos-privacy preset balanced
test -s /etc/systemd/resolved.conf.d/80-pcos-dns.conf
dconf update
# The look-and-feel defaults compiled: desktop (distro) and login screen (gdm)
test -f /etc/dconf/db/gdm && test -f /etc/dconf/db/distro

### Temp Monitor (docs/DESIGN.md §9), built in the Containerfile's temp-monitor stage
# Folder publish (not single-file), so nothing is unpacked into home folders at run time.
cp -a /ctx/apps/temp-monitor /usr/lib/temp-monitor
chmod 0755 /usr/lib/temp-monitor/TempMonitor
ln -sf /usr/lib/temp-monitor/TempMonitor /usr/bin/temp-monitor
install -Dm0644 /ctx/apps/temp-monitor.png /usr/share/icons/hicolor/512x512/apps/temp-monitor.png
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
if command -v desktop-file-validate >/dev/null; then desktop-file-validate /usr/share/applications/temp-monitor.desktop /usr/share/applications/rudramos-app-store.desktop; fi
# "App Store" opens Bluefin's Bazaar: fail here if the base image stops shipping it
grep -rqs "io.github.kolunmi.Bazaar" /usr/share/flatpak/preinstall.d/ || { echo "ERROR: base image no longer preinstalls Bazaar; update pcos-app-store" >&2; exit 1; }
# Install / remove prompts say who is asking and what, e.g. "The App Store (or a terminal) wants to
# install an app for everyone on this PC: app/org.mozilla.firefox/x86_64/stable from flathub"
python3 /ctx/polkit-messages.py /usr/share/polkit-1/actions/org.freedesktop.Flatpak.policy
# drivetemp (SATA/USB drive temperatures) is loaded at boot by modules-load.d
find /usr/lib/modules -name 'drivetemp.ko*' | grep -q . || { echo "ERROR: kernel has no drivetemp module" >&2; exit 1; }
# Runs without a display and prints whatever sensors the build container can see
timeout 120 /usr/bin/temp-monitor --print
# Fan control service (root): profile "Auto" by default, so it changes nothing until the user
# picks a fan profile. Lowering fan safety limits needs admin approval (polkit).
install -Dm0644 /ctx/apps/temp-monitor-packaging/temp-monitor-fans.service /usr/lib/systemd/system/temp-monitor-fans.service
install -Dm0644 /ctx/apps/temp-monitor-packaging/com.github.venkateshguggilla.tempmonitor.policy \
    /usr/share/polkit-1/actions/com.github.venkateshguggilla.tempmonitor.policy
systemctl enable temp-monitor-fans.service
timeout 60 /usr/bin/temp-monitor fan --help >/dev/null
# Background monitor (every user, while logged in): history + overheat / stalled-fan notifications
install -Dm0644 /ctx/apps/temp-monitor-packaging/temp-monitor-background.service /usr/lib/systemd/user/temp-monitor-background.service
systemctl --global enable temp-monitor-background.service

### PC Cleaner (docs/DESIGN.md §9.2), from the Containerfile's pc-cleaner stage
# Python + Tk; ttkbootstrap is pinned by version and hash. The app never runs as root: the
# "System maintenance" items go through pccleaner-system with admin approval (polkit).
dnf5 install -y python3-tkinter python3-pillow-tk python3-pip
PCC=/ctx/apps/pc-cleaner
install -d /usr/lib/pc-cleaner
cp -a "${PCC}/pccleaner" "${PCC}/assets" /usr/lib/pc-cleaner/
cat >/tmp/pc-cleaner-requirements.txt <<'EOF'
ttkbootstrap==2.2.3 --hash=sha256:00db93ee9d064d2d7bcac2158ca2d852f2844277d0da0a526163077ca9623417
EOF
python3 -m pip install --no-cache-dir --no-deps --require-hashes --target /usr/lib/pc-cleaner/vendor \
    -r /tmp/pc-cleaner-requirements.txt
install -Dm0755 "${PCC}/packaging/linux/pc-cleaner" /usr/bin/pc-cleaner
install -Dm0755 "${PCC}/packaging/linux/pccleaner-system" /usr/libexec/pccleaner/pccleaner-system
install -Dm0644 "${PCC}/packaging/linux/com.github.venkateshguggilla.pccleaner.policy" \
    /usr/share/polkit-1/actions/com.github.venkateshguggilla.pccleaner.policy
install -Dm0644 "${PCC}/packaging/linux/pc-cleaner.desktop" /usr/share/applications/pc-cleaner.desktop
install -Dm0644 "${PCC}/assets/pccleaner.png" /usr/share/icons/hicolor/256x256/apps/pc-cleaner.png
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
# Precompile: /usr is read-only on the running system
python3 -m compileall -q /usr/lib/pc-cleaner
# Its tests (the Linux ones run here; Windows-only ones skip) and a start-up check
(cd "${PCC}" && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t .)
PYTHONPATH=/usr/lib/pc-cleaner/vendor:/usr/lib/pc-cleaner python3 -B -c 'import pccleaner.gui'
/usr/bin/pc-cleaner list >/dev/null
if command -v desktop-file-validate >/dev/null; then desktop-file-validate /usr/share/applications/pc-cleaner.desktop; fi

### Android phone (docs/DESIGN.md §9.3). Control Center → Phone.
# Phone link: GSConnect (KDE Connect protocol) for notifications, texts, calls, files and
# clipboard. Bluefin ships it; switch it on by default, keeping Bluefin's other extensions. Its
# network ports open only on Home networks (pcos-network share phone).
GSCONNECT=/usr/share/gnome-shell/extensions/gsconnect@andyholmes.github.io
[[ -f "${GSCONNECT}/metadata.json" ]] || dnf5 install -y gnome-shell-extension-gsconnect
[[ -f "${GSCONNECT}/metadata.json" ]] || { echo "ERROR: GSConnect is not installed" >&2; exit 1; }
python3 /ctx/gnome-list-add.py /etc/dconf/db/distro.d/zz8-rudramos-extensions enabled-extensions gsconnect@andyholmes.github.io
dconf update
# Phone screen: scrcpy's own build (Containerfile scrcpy stage) behind pcos-phone. adb talks to
# the phone over USB once USBGuard and the phone allow it; 70-rudramos-android.rules gives the
# logged-in user access to the phone's debugging interface (Fedora has no android-udev-rules).
udevadm verify --resolve-names=never /usr/lib/udev/rules.d/70-rudramos-android.rules
install -d /usr/lib/scrcpy
install -m0755 /ctx/apps/scrcpy/scrcpy /ctx/apps/scrcpy/adb /usr/lib/scrcpy/
install -m0644 /ctx/apps/scrcpy/scrcpy-server /ctx/apps/scrcpy/disconnected.png /ctx/apps/scrcpy/LICENSE /usr/lib/scrcpy/
install -Dm0644 /ctx/apps/scrcpy/scrcpy.1 /usr/share/man/man1/scrcpy.1
install -Dm0644 /ctx/apps/scrcpy/scrcpy.png /usr/share/icons/hicolor/256x256/apps/rudramos-phone-screen.png
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
chmod 0755 /usr/bin/pcos-phone
/usr/lib/scrcpy/scrcpy --version
# adb keeps its keys in ~/.android; the build has no home folder (/root -> missing /var/roothome)
HOME=/tmp /usr/lib/scrcpy/adb version
if command -v desktop-file-validate >/dev/null; then desktop-file-validate /usr/share/applications/rudramos-phone-screen.desktop; fi

### Check the Control Center loads (imports GTK/Adw, no display needed)
python3 -B -c 'import sys; sys.path.insert(0, "/usr/lib/pcos-control"); import pcos_control.app'

### Updates
# Bluefin already enables automatic updates (uupd.timer: bootc image + Flatpaks,
# applied on next reboot), so nothing to enable here.
