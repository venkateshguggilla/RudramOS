#!/bin/bash
# Tests for system_files/usr/libexec/pcos/pcos-update with a stubbed bootc.
# Run: bash tests/test-update.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/libexec/pcos/pcos-update"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0
mkdir -p "${work}/bin"

assert() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}

cat >"${work}/bin/bootc" <<'STUB'
#!/bin/bash
echo "$*" >>"${CALLS}"
case "${BOOTC_FAIL:-}" in
lock) echo "error: Failed to acquire lock on sysroot" >&2; exit 1 ;;
net) echo "error: pulling image: connection refused" >&2; exit 1 ;;
esac
STUB
chmod +x "${work}/bin/bootc"
export PATH="${work}/bin:${PATH}" CALLS="${work}/calls" PCOS_TEST=1

assert "upgrade downloads with bootc upgrade" bash -c "bash '${TOOL}' upgrade && grep -qx 'upgrade --quiet' '${CALLS}'"
assert "rollback uses bootc rollback" bash -c "bash '${TOOL}' rollback && grep -qx 'rollback' '${CALLS}'"
assert "no download: friendly message, exit 3" bash -c "out=\$(BOOTC_FAIL=net bash '${TOOL}' upgrade 2>&1); [ \$? = 3 ] && [ \"\$(tail -n1 <<<\"\${out}\")\" = \"The update couldn't be downloaded. Check the internet connection and try again.\" ]"
assert "already updating in the background: says so" bash -c "BOOTC_FAIL=lock bash '${TOOL}' upgrade 2>&1 | tail -n1 | grep -q 'already being installed'"
assert "unknown command refused" bash -c "bash '${TOOL}' reboot; [ \$? = 2 ]"
assert "not root refused" bash -c "PCOS_TEST= bash '${TOOL}' upgrade; [ \$? = 2 ]"

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
