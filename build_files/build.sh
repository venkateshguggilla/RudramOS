#!/bin/bash
# PC OS image build script. Runs inside the Containerfile build (see Containerfile).

set -ouex pipefail

IMAGE_REPO="ghcr.io/venkateshguggilla/pcos"
SIGNING_PUBKEY="/etc/pki/containers/pcos.pub"

### System files
# Copy the contents of system_files/ in the git repo to /
cp -avf "/ctx/system_files"/. /

### Branding (Phase 1 basics; full branding in Phase 12)
sed -i 's/^PRETTY_NAME=.*/PRETTY_NAME="PC OS"/' /usr/lib/os-release
mkdir -p /usr/share/pcos
date -u +%Y%m%d > /usr/share/pcos/build-date

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
jq --arg repo "${IMAGE_REPO}" --arg key "${SIGNING_PUBKEY}" \
    '.transports.docker[$repo] = [{
        "type": "sigstoreSigned",
        "keyPath": $key,
        "signedIdentity": {"type": "matchRepository"}
    }]' "${POLICY}" > /tmp/policy.json
install -m644 /tmp/policy.json "${POLICY}"

mkdir -p /etc/containers/registries.d
cat > /etc/containers/registries.d/pcos.yaml <<EOF
docker:
  ${IMAGE_REPO}:
    use-sigstore-attachments: true
EOF

### Packages
# Phase 1 adds no packages. Later phases install them here, e.g.:
# dnf5 install -y usbguard fapolicyd pam-u2f

### Updates
# Bluefin already enables automatic updates (uupd.timer: bootc image + Flatpaks,
# applied on next reboot), so nothing to enable here.
