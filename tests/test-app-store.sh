#!/bin/bash
# Tests for system_files/usr/libexec/pcos/pcos-app-store with stubbed flatpak and notify-send.
# Run: bash tests/test-app-store.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/libexec/pcos/pcos-app-store"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0
mkdir -p "${work}/bin"

assert() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}

cat >"${work}/bin/flatpak" <<'STUB'
#!/bin/bash
echo "$*" >>"${CALLS}"
case "$1" in
info) [[ -e "${INSTALLED}" ]] ;;
install)
    case "${INSTALL_RESULT:-ok}" in
    ok) touch "${INSTALLED}" ;;
    offline) echo "error: Unable to load summary from remote flathub: Could not resolve hostname" >&2; exit 1 ;;
    cancel) echo "error: Not authorized" >&2; exit 1 ;;
    esac ;;
run) exit 0 ;;
esac
STUB
cat >"${work}/bin/notify-send" <<'STUB'
#!/bin/bash
echo "$*" >>"${NOTES}"
STUB
chmod +x "${work}/bin/flatpak" "${work}/bin/notify-send"
export PATH="${work}/bin:${PATH}" CALLS="${work}/calls" NOTES="${work}/notes" INSTALLED="${work}/installed"
reset() { rm -f "${CALLS}" "${NOTES}" "${INSTALLED}"; }

reset; touch "${INSTALLED}"
assert "installed: opens Bazaar straight away" bash -c "bash '${TOOL}' && grep -qx 'run io.github.kolunmi.Bazaar' '${CALLS}' && ! grep -q install '${CALLS}'"
reset
assert "missing: installs from Flathub, then opens it" bash -c "bash '${TOOL}' && grep -q 'install --system --noninteractive -y flathub io.github.kolunmi.Bazaar' '${CALLS}' && grep -qx 'run io.github.kolunmi.Bazaar' '${CALLS}'"
assert "and says what it's doing" grep -q "Setting up the App Store" "${NOTES}"
reset
assert "offline: tells the user to connect, exit 1" bash -c "INSTALL_RESULT=offline bash '${TOOL}'; [ \$? = 1 ] && grep -q 'No internet connection' '${NOTES}' && ! grep -q '^run' '${CALLS}'"
reset
assert "approval cancelled: says to try again" bash -c "INSTALL_RESULT=cancel bash '${TOOL}'; [ \$? = 1 ] && grep -q 'try again' '${NOTES}'"

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
