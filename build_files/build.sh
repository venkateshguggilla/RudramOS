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
chmod 0755 /usr/bin/pcos-app-guard /usr/bin/pcos-browser-extensions /usr/libexec/pcos/pcos-app-guard-notify /usr/bin/pcos-control /usr/libexec/pcos/pcos-terminal-run /usr/bin/pcos-admin-mode /usr/bin/pcos-disk-security /usr/bin/pcos-driver-assistant /usr/libexec/pcos/pcos-gpu-detect /usr/libexec/pcos/pcos-gpu-switch

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

### Check the Control Center loads (imports GTK/Adw, no display needed)
python3 -B -c 'import sys; sys.path.insert(0, "/usr/lib/pcos-control"); import pcos_control.app'

### Updates
# Bluefin already enables automatic updates (uupd.timer: bootc image + Flatpaks,
# applied on next reboot), so nothing to enable here.
