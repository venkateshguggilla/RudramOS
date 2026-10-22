#!/bin/bash
# Tests for system_files/usr/libexec/pcos/pcos-usb-firstboot with a stubbed usbguard.
# Run: bash tests/test-usb-firstboot.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/libexec/pcos/pcos-usb-firstboot"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0
mkdir -p "${work}/bin"

assert() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}

# What "usbguard generate-policy" prints for a desktop: hub, keyboard without serial, mouse
cat >"${work}/bin/usbguard" <<'STUB'
#!/bin/bash
[[ "$1" == generate-policy ]] || exit 1
cat <<'RULES'
allow id 1d6b:0002 serial "0000:00:14.0" name "xHCI Host Controller" hash "jEP/6WzviqdJ5VSeTUY8PatCNBKeaREvo2OqdplND/o=" parent-hash "G1ehGQdrl3dJ9HvW9w2HdC//pk87pKzFE1WY25bq8k4=" with-interface 09:00:00 with-connect-type ""
allow id 046d:c31c serial "" name "USB Keyboard" hash "6/mVqb6hXb6BOoXgXiDdhSaPU8HUzIwW5iWE5aNWUrE=" parent-hash "jEP/6WzviqdJ5VSeTUY8PatCNBKeaREvo2OqdplND/o=" via-port "1-2" with-interface { 03:01:01 03:00:00 } with-connect-type "hotplug"
allow id 046d:c077 serial "" name "USB Optical Mouse" hash "kN6Y2bQ1pOE4p5Z0sbT4yL7Xc6m0uT9tYvT+Cq3m4F8=" parent-hash "jEP/6WzviqdJ5VSeTUY8PatCNBKeaREvo2OqdplND/o=" via-port one-of { "1-3" "3-3" } with-interface 03:01:02 with-connect-type "hotplug"
RULES
STUB
chmod +x "${work}/bin/usbguard"
export PATH="${work}/bin:${PATH}" PCOS_USBGUARD_RULES="${work}/rules.conf"
R="${work}/rules.conf"

: >"${R}"
bash "${TOOL}" >/dev/null
assert "first start: trusts the connected devices" test "$(grep -c '^allow' "${R}")" = 3
assert "no port numbers left" bash -c "! grep -q 'via-port' '${R}'"
assert "no parent hashes left" bash -c "! grep -q 'parent-hash' '${R}'"
assert "no connect types left" bash -c "! grep -q 'with-connect-type' '${R}'"
assert "keyboard still identified by id, name and hash" \
    grep -qx 'allow id 046d:c31c serial "" name "USB Keyboard" hash "6/mVqb6hXb6BOoXgXiDdhSaPU8HUzIwW5iWE5aNWUrE=" with-interface { 03:01:01 03:00:00 }' "${R}"
assert "mouse's interface kept" grep -q 'name "USB Optical Mouse" hash "[^"]*" with-interface 03:01:02$' "${R}"

# An existing PC from before this fix: its rules are cleaned on the next start, nothing else
usbguard generate-policy >"${R}"
echo 'allow id 1050:0407 serial "" name "YubiKey" hash "abc=" with-interface { 03:00:00 0b:00:00 }' >>"${R}"
before_yubikey=$(grep YubiKey "${R}")
bash "${TOOL}" >/dev/null
assert "existing rules: port details removed" bash -c "! grep -qE 'via-port|parent-hash|with-connect-type' '${R}'"
assert "existing rules: still 4 rules" test "$(grep -c '^allow' "${R}")" = 4
assert "a rule without port details is unchanged" grep -qxF "${before_yubikey}" "${R}"
cp "${R}" "${work}/after-first"
bash "${TOOL}" >/dev/null
assert "running again changes nothing" cmp -s "${R}" "${work}/after-first"

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
