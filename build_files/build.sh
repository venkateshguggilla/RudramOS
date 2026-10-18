#!/bin/bash
# PC OS image build script. Runs inside the Containerfile build (see Containerfile).

set -ouex pipefail

GPU="${GPU:-none}"
REGISTRY="ghcr.io/venkateshguggilla"
# All image variants: a PC may switch between them, so each must be signature-checked
IMAGE_REPOS=("${REGISTRY}/pcos" "${REGISTRY}/pcos-nvidia" "${REGISTRY}/pcos-nvidia-legacy")
SIGNING_PUBKEY="/etc/pki/containers/pcos.pub"

### System files
# Copy the contents of system_files/ in the git repo to /
cp -avf "/ctx/system_files"/. /
chmod 0755 /usr/bin/pcos-admin-mode /usr/bin/pcos-disk-security /usr/bin/pcos-driver-assistant /usr/libexec/pcos/pcos-gpu-detect /usr/libexec/pcos/pcos-gpu-switch

### Branding (Phase 1 basics; full branding in Phase 12)
sed -i 's/^PRETTY_NAME=.*/PRETTY_NAME="PC OS"/' /usr/lib/os-release
mkdir -p /usr/share/pcos
date -u +%Y%m%d > /usr/share/pcos/build-date

### GPU drivers for this image variant
/ctx/gpu.sh

### Only accept PC OS images signed with our cosign key
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

### Admin approval modes (docs/DESIGN.md §4.3)
# sudo and polkit (all desktop admin prompts) authenticate through /etc/pam.d/pcos-admin,
# which pcos-admin-mode switches between the Standard and Strong templates.
for service in sudo polkit-1; do
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

### Updates
# Bluefin already enables automatic updates (uupd.timer: bootc image + Flatpaks,
# applied on next reboot), so nothing to enable here.
