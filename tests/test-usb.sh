#!/bin/bash
# Tests for system_files/usr/bin/pcos-usb with a stubbed usbguard and systemctl.
# Run: bash tests/test-usb.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/bin/pcos-usb"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0
mkdir -p "${work}/bin" "${work}/rules.d"

cat >"${work}/bin/usbguard" <<'EOF'
#!/bin/bash
echo "$*" >> "${USBGUARD_LOG}"
case "$1" in
list-devices)
    lines=(
'1: allow id 1d6b:0002 serial "0000:00:14.0" name "xHCI Host Controller" with-interface 09:00:00'
'7: block id 0781:5581 serial "4C53" name "Ultra" hash "a" parent-hash "b" with-interface 08:06:50 with-connect-type "hotplug"'
'8: block id 1050:0407 serial "" name "YubiKey OTP+FIDO+CCID" hash "c" parent-hash "d" with-interface { 03:01:01 03:00:00 0b:00:00 } with-connect-type "hotplug"'
'9: block id 1b4f:9206 serial "" name "Flash Disk" hash "e" parent-hash "f" with-interface { 08:06:50 03:01:01 } with-connect-type "hotplug"'
    )
    for l in "${lines[@]}"; do
        if [[ "${2:-}" == --blocked && "$l" != *": block "* ]]; then continue; fi
        echo "$l"
    done ;;
list-rules) echo '1: allow id 1d6b:0002 serial "0000:00:14.0" name "xHCI Host Controller"' ;;
esac
EOF
cat >"${work}/bin/systemctl" <<'EOF'
#!/bin/bash
echo "$*" >> "${SYSTEMCTL_LOG}"
[[ "$1" == is-active ]] && exit 0
exit 0
EOF
chmod +x "${work}/bin/"*

export PATH="${work}/bin:${PATH}" PCOS_TEST_ROOT=1
export USBGUARD_LOG="${work}/usbguard.log" SYSTEMCTL_LOG="${work}/systemctl.log"
export MODE_FILE="${work}/usb-mode" RULES_DIR="${work}/rules.d" DESCRIBE="${ROOT}/system_files/usr/libexec/pcos/pcos-usb-describe"

assert() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}
ug_has() { grep -qxF -- "$1" "${USBGUARD_LOG}"; }

assert "status shows default mode ask" bash -c "bash '${TOOL}' status | grep -q 'USB protection: ask'"
assert "status counts 3 blocked" bash -c "bash '${TOOL}' status | grep -q 'Blocked now: 3'"
assert "devices describes the BadUSB stick as danger" bash -c "bash '${TOOL}' devices | grep -E '^9 +block +Flash Disk: Keyboard \+ Storage \[danger\]'"

: >"${USBGUARD_LOG}"
assert "allow once" bash "${TOOL}" allow 7
assert "  temporary allow-device" ug_has "allow-device 7"
assert "allow permanently" bash "${TOOL}" allow 7 --permanent
assert "  permanent allow-device -p" ug_has "allow-device -p 7"
: >"${USBGUARD_LOG}"
assert "security key is always permanent" bash "${TOOL}" allow 8
assert "  allow-device -p for the YubiKey" ug_has "allow-device -p 8"
assert "unknown id refused" bash -c "! bash '${TOOL}' allow 42"
assert "non-numeric id refused" bash -c "! bash '${TOOL}' allow abc"

assert "block a device" bash -c "bash '${TOOL}' block 7 && grep -qx 'block-device 7' '${USBGUARD_LOG}'"
assert "forget a rule" bash -c "bash '${TOOL}' forget 1 && grep -qx 'remove-rule 1' '${USBGUARD_LOG}'"

assert "mode allow-input writes match-all HID rule" bash -c "bash '${TOOL}' mode allow-input && grep -qx 'allow with-interface match-all { 03:01:01 03:01:02 03:00:00 }' '${RULES_DIR}/50-pcos-input.conf'"
assert "  usbguard restarted" grep -qx "restart usbguard.service" "${SYSTEMCTL_LOG}"
assert "mode off replaces it with allow-all" bash -c "bash '${TOOL}' mode off && [ ! -e '${RULES_DIR}/50-pcos-input.conf' ] && grep -qx allow '${RULES_DIR}/99-pcos-off.conf'"
assert "mode ask removes both" bash -c "bash '${TOOL}' mode ask && [ -z \"\$(ls '${RULES_DIR}')\" ] && grep -qx ask '${MODE_FILE}'"
assert "bad mode refused" bash -c "! bash '${TOOL}' mode sometimes"
assert "not root refused" bash -c "! PCOS_TEST_ROOT=0 bash '${TOOL}' allow 7"

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
