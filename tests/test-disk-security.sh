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

echo
if (( failures > 0 )); then
    echo "${failures} test(s) failed"
    exit 1
fi
echo "all tests passed"
