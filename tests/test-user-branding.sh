#!/bin/bash
# Tests for system_files/usr/libexec/pcos/pcos-user-branding with a stubbed gsettings.
# Run: bash tests/test-user-branding.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/libexec/pcos/pcos-user-branding"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0
mkdir -p "${work}/bin" "${work}/db"

assert() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}

# Fake gsettings: one file per "schema key" holding the user's value; no file = default
cat >"${work}/bin/gsettings" <<'STUB'
#!/bin/bash
f="${DB}/$2.$3"
case "$1" in
get)
    [[ "$2" == org.gnome.desktop.screensaver && "$3" == picture-uri-dark ]] && { echo "No such key" >&2; exit 1; }
    if [[ -f "$f" ]]; then cat "$f"; else echo "'file:///usr/share/backgrounds/rudramos/rudramos-trishul.jpg'"; fi ;;
reset) rm -f "$f"; echo "$2.$3" >>"${DB}/resets" ;;
esac
STUB
chmod +x "${work}/bin/gsettings"
export PATH="${work}/bin:${PATH}" DB="${work}/db"

echo "'file:///usr/share/backgrounds/bluefin/06-bluefin.xml'" >"${DB}/org.gnome.desktop.background.picture-uri"
echo "'file:///usr/share/backgrounds/bluefin/06-bluefin.xml'" >"${DB}/org.gnome.desktop.background.picture-uri-dark"
echo "'file:///usr/share/backgrounds/bluefin/10-bluefin.xml'" >"${DB}/org.gnome.desktop.screensaver.picture-uri"
bash "${TOOL}" >/dev/null
assert "Bluefin desktop wallpaper reset" grep -qx org.gnome.desktop.background.picture-uri "${DB}/resets"
assert "Bluefin dark wallpaper reset" grep -qx org.gnome.desktop.background.picture-uri-dark "${DB}/resets"
assert "Bluefin lock screen reset" grep -qx org.gnome.desktop.screensaver.picture-uri "${DB}/resets"

rm -f "${DB}"/*
echo "'file:///home/me/Pictures/holiday.jpg'" >"${DB}/org.gnome.desktop.background.picture-uri"
bash "${TOOL}" >/dev/null
assert "a wallpaper the user picked is kept" grep -q holiday "${DB}/org.gnome.desktop.background.picture-uri"
assert "nothing reset" test ! -e "${DB}/resets"
assert "a missing key doesn't fail the script" bash "${TOOL}"

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
