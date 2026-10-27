#!/bin/bash
# Tests for the boot-drive detection in system_files/usr/bin/pcos-disk-security.
# Run: bash tests/test-disk-security.sh

set -uo pipefail
TOOL="$(cd "$(dirname "$0")/.." && pwd)/system_files/usr/bin/pcos-disk-security"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0

# Load only the functions (everything above the command dispatch)
# shellcheck disable=SC1090
source <(sed -n '/^set -euo pipefail/,/^cmd=/p' "${TOOL}" | sed '$d')
set +e

check() {
    local desc="$1" expected="$2" cmdline="$3"
    printf '%s\n' "${cmdline}" >"${work}/cmdline"
    local got
    got=$(CMDLINE_FILE="${work}/cmdline" luks_uuid)
    if [[ "${got}" == "${expected}" ]]; then
        echo "ok   ${desc}"
    else
        echo "FAIL ${desc}: expected '${expected}', got '${got}'"
        failures=$((failures + 1))
    fi
}

U=0b7c3a6e-1f2d-4c5b-9a8e-123456789abc
check "rd.luks.uuid" "${U}" "BOOT_IMAGE=(hd0,gpt2)/boot/ostree/vmlinuz root=UUID=x rd.luks.uuid=${U} rhgb quiet"
check "rd.luks.uuid with luks- prefix" "${U}" "root=UUID=x rd.luks.uuid=luks-${U} quiet"
check "rd.luks.name" "${U}" "root=/dev/mapper/root rd.luks.name=${U}=root quiet"
check "not encrypted" "" "BOOT_IMAGE=/vmlinuz root=UUID=x rw quiet"

# --secrets-stdin: only PASSWORD / NEWPIN / PIN become environment variables for systemd-cryptenroll
expect() {
    if [[ "$2" == "$3" ]]; then echo "ok   $1"; else echo "FAIL $1: expected '$3', got '$2'"; failures=$((failures + 1)); fi
}
unset PASSWORD NEWPIN PIN EVIL
read_secrets 2>"${work}/err" <<'EOF'
PASSWORD=my disk pass = with spaces
NEWPIN=4821
EVIL=$(touch /tmp/pwned)
PIN=123456
EOF
expect "passphrase with spaces and '='" "${PASSWORD:-}" "my disk pass = with spaces"
expect "TPM PIN" "${NEWPIN:-}" "4821"
expect "security key PIN" "${PIN:-}" "123456"
expect "unknown names are ignored" "${EVIL:-unset}" "unset"
expect "and reported by name" "$(grep -c 'Ignored unknown secret name: EVIL' "${work}/err")" "1"
expect "without printing the value" "$(grep -c 'pwned' "${work}/err")" "0"
unset PIN
read_secrets < <(printf 'PIN=9999')
expect "a last line without newline is read" "${PIN:-}" "9999"
YES=yes
if confirm "Continue?" </dev/null; then expect "--yes answers the question" ok ok; else expect "--yes answers the question" no ok; fi
YES=no
if echo n | confirm "Continue?" >/dev/null 2>&1; then expect "'n' means no" yes no; else expect "'n' means no" no no; fi

echo
if (( failures > 0 )); then
    echo "${failures} test(s) failed"
    exit 1
fi
echo "all tests passed"
