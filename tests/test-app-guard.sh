#!/bin/bash
# Tests for the rule generation and approval list in system_files/usr/bin/pcos-app-guard.
# fapolicyd-cli is stubbed (it records calls). Run: bash tests/test-app-guard.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/bin/pcos-app-guard"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0

mkdir -p "${work}/bin" "${work}/rules.d" "${work}/trust.d" "${work}/home/venky/.config" "${work}/home/anita"
cat >"${work}/bin/fapolicyd-cli" <<'EOF'
#!/bin/bash
echo "$*" >> "${CALLS}"
EOF
chmod +x "${work}/bin/fapolicyd-cli"
# venky has a localized Downloads folder; anita uses the defaults
cat >"${work}/home/venky/.config/user-dirs.dirs" <<'EOF'
XDG_DESKTOP_DIR="$HOME/Desktop"
XDG_DOWNLOAD_DIR="$HOME/Téléchargements"
EOF
cat >"${work}/passwd" <<EOF
root:x:0:0:root:/root:/bin/bash
polkitd:x:998:996:User for polkitd:/:/sbin/nologin
venky:x:1000:1000:Venky:${work}/home/venky:/bin/bash
anita:x:1001:1001::${work}/home/anita:/bin/zsh
svc:x:1002:1002::/var/lib/svc:/usr/sbin/nologin
nobody:x:65534:65534:Kernel Overflow User:/:/sbin/nologin
EOF

export PATH="${work}/bin:${PATH}" PCOS_TEST_ROOT=1 CALLS="${work}/calls"
export RULES_DIR="${work}/rules.d" TRUST_FILE="${work}/trust.d/pcos-approved" PASSWD_FILE="${work}/passwd"
RULES="${RULES_DIR}/50-pcos-users.rules"

assert() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}

bash "${TOOL}" regenerate-rules
assert "rules file generated" test -s "${RULES}"
assert "venky localized Downloads blocked" grep -qxF "deny_syslog perm=execute all : dir=${work}/home/venky/Téléchargements/" "${RULES}"
assert "venky Desktop blocked" grep -qxF "deny_syslog perm=execute all : dir=${work}/home/venky/Desktop/" "${RULES}"
assert "venky user Flatpaks blocked" grep -qxF "deny_syslog perm=execute all : dir=${work}/home/venky/.local/share/flatpak/" "${RULES}"
assert "anita default Downloads blocked" grep -qxF "deny_syslog perm=execute all : dir=${work}/home/anita/Downloads/" "${RULES}"
assert "system and nologin users skipped" bash -c "! grep -qE 'root|polkitd|svc|nobody' '${RULES}' || ! grep -qE 'dir=/(root|var/lib/svc)/' '${RULES}'"
assert "every rule line is well-formed" bash -c "grep -v '^#' '${RULES}' | grep -vqE '^deny_syslog perm=execute all : dir=/.*/$' && exit 1 || exit 0"
# Security review: user-dirs.dirs is written by the user, the rules by root at boot
mkdir -p "${work}/home/mallory/.config" "${work}/home/eve/.config" "${work}/home/zoe/.config"
echo 'XDG_DOWNLOAD_DIR="/usr"' >"${work}/home/mallory/.config/user-dirs.dirs"
printf '%s\n' 'XDG_DOWNLOAD_DIR="$HOME/x/ trust=1 : all"' 'XDG_DESKTOP_DIR="$HOME/../anita/Desktop"' >"${work}/home/eve/.config/user-dirs.dirs"
echo 'XDG_DOWNLOAD_DIR="$HOME/Mes Téléchargements"' >"${work}/home/zoe/.config/user-dirs.dirs"
cat >>"${work}/passwd" <<EOF
mallory:x:1003:1003::${work}/home/mallory:/bin/bash
eve:x:1004:1004::${work}/home/eve:/bin/bash
zoe:x:1005:1005::${work}/home/zoe:/bin/bash
EOF
bash "${TOOL}" regenerate-rules
assert "a Downloads folder outside the home is ignored" bash -c "! grep -q 'dir=/usr/' '${RULES}' && grep -qxF 'deny_syslog perm=execute all : dir=${work}/home/mallory/Downloads/' '${RULES}'"
assert "rule syntax in a folder name is ignored" bash -c "! grep -q 'trust=1' '${RULES}' && grep -qxF 'deny_syslog perm=execute all : dir=${work}/home/eve/Downloads/' '${RULES}'"
assert "'..' out of the home is ignored" bash -c "! grep -q '/eve/../' '${RULES}' && grep -qxF 'deny_syslog perm=execute all : dir=${work}/home/eve/Desktop/' '${RULES}'"
assert "a folder name with a space falls back to the default" grep -qxF "deny_syslog perm=execute all : dir=${work}/home/zoe/Downloads/" "${RULES}"
assert "still every rule line well-formed" bash -c "grep -v '^#' '${RULES}' | grep -vqE '^deny_syslog perm=execute all : dir=/[^ ]*/$' && exit 1 || exit 0"

assert "base rules: root unrestricted first" bash -c "head -n 5 '${ROOT}/system_files/usr/share/pcos/fapolicyd/10-pcos-base.rules' | grep -q '^allow perm=any uid=0 : all'"
assert "final rules end with allow all" bash -c "tail -n1 '${ROOT}/system_files/usr/share/pcos/fapolicyd/90-pcos-final.rules' | grep -qx 'allow perm=any all : all'"

# Approval list parsing (trust file: path size sha256; paths may contain spaces)
printf '%s\n' "/var/home/venky/Downloads/tool.AppImage 1234 abcd" "/var/home/venky/Downloads/My App/run 99 ef01" >"${TRUST_FILE}"
assert "list shows approved paths" bash -c "bash '${TOOL}' list | grep -qxF '/var/home/venky/Downloads/My App/run'"
assert "status counts approvals" bash -c "bash '${TOOL}' status | grep -q 'Approved programs: 2'"

touch "${work}/home/venky/newtool"
assert "approve calls fapolicyd-cli add + update" bash -c "bash '${TOOL}' approve '${work}/home/venky/newtool' && grep -q -- '--file add .*newtool --trust-file pcos-approved' '${CALLS}' && grep -qx -- '--update' '${CALLS}'"
assert "approve of missing file fails" bash -c "! bash '${TOOL}' approve '${work}/missing'"
assert "revoke of unapproved file fails" bash -c "! bash '${TOOL}' revoke '${work}/home/venky/newtool'"
assert "revoke of approved file calls delete" bash -c "bash '${TOOL}' revoke '/var/home/venky/Downloads/tool.AppImage' && grep -q -- '--file delete /var/home/venky/Downloads/tool.AppImage' '${CALLS}'"
assert "not root refused" bash -c "! PCOS_TEST_ROOT=0 bash '${TOOL}' approve '${work}/home/venky/newtool'"

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
