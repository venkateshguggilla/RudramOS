#!/bin/bash
# RudramOS image build script. Runs inside the Containerfile build (see Containerfile).

set -ouex pipefail

GPU="${GPU:-none}"
REGISTRY="ghcr.io/venkateshguggilla"
# All image variants: a PC may switch between them, so each must be signature-checked
IMAGE_REPOS=("${REGISTRY}/pcos" "${REGISTRY}/pcos-nvidia" "${REGISTRY}/pcos-nvidia-legacy")
SIGNING_PUBKEY="/etc/pki/containers/pcos.pub"

### System files
# Copy the contents of system_files/ in the git repo to /
cp -avf "/ctx/system_files"/. /
chmod 0755 /usr/bin/pcos-privacy /usr/bin/pcos-killswitch /usr/bin/pcos-usb /usr/libexec/pcos/pcos-usb-describe /usr/libexec/pcos/pcos-usb-watch /usr/libexec/pcos/pcos-usb-prompt /usr/libexec/pcos/pcos-usb-firstboot /usr/bin/pcos-network /usr/libexec/pcos/pcos-network-prompt /usr/lib/NetworkManager/dispatcher.d/50-pcos-network-trust /usr/bin/pcos-app-guard /usr/bin/pcos-browser-extensions /usr/libexec/pcos/pcos-app-guard-notify /usr/bin/pcos-control /usr/libexec/pcos/pcos-terminal-run /usr/bin/pcos-admin-mode /usr/bin/pcos-disk-security /usr/bin/pcos-driver-assistant /usr/libexec/pcos/pcos-gpu-detect /usr/libexec/pcos/pcos-gpu-switch

### Branding (Phase 1 basics; full branding in Phase 12)
sed -i 's/^PRETTY_NAME=.*/PRETTY_NAME="RudramOS"/' /usr/lib/os-release
mkdir -p /usr/share/pcos
date -u +%Y%m%d > /usr/share/pcos/build-date

### GPU drivers for this image variant
/ctx/gpu.sh

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

### Check the Control Center loads (imports GTK/Adw, no display needed)
python3 -B -c 'import sys; sys.path.insert(0, "/usr/lib/pcos-control"); import pcos_control.app'

### Updates
# Bluefin already enables automatic updates (uupd.timer: bootc image + Flatpaks,
# applied on next reboot), so nothing to enable here.
