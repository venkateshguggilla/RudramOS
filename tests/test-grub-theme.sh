#!/bin/bash
# Tests for system_files/usr/libexec/pcos/pcos-grub-theme against a fake /boot/grub2.
# Run: bash tests/test-grub-theme.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/libexec/pcos/pcos-grub-theme"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0

assert() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}

export PCOS_GRUB_THEME_SRC="${work}/src" PCOS_GRUB_DIR="${work}/grub2" PCOS_NO_GRUB_THEME="${work}/no-grub-theme"
export PCOS_NO_WINDOWS_ENTRY="${work}/no-windows-entry"
mkdir -p "${PCOS_GRUB_THEME_SRC}" "${PCOS_GRUB_DIR}"
echo "theme" >"${PCOS_GRUB_THEME_SRC}/theme.txt"
echo "font" >"${PCOS_GRUB_THEME_SRC}/unicode.pf2"
echo "v1" >"${PCOS_GRUB_THEME_SRC}/.stamp"
CFG="${PCOS_GRUB_DIR}/user.cfg"
echo 'GRUB2_PASSWORD=grub.pbkdf2.sha512.10000.ABC' >"${CFG}"

run() { bash "${TOOL}"; }

run >/dev/null
assert "installs the theme files" test -f "${PCOS_GRUB_DIR}/themes/rudramos/theme.txt"
assert "adds one guarded block to user.cfg" bash -c "[ \"\$(grep -c '^### BEGIN RudramOS boot menu theme$' '${CFG}')\" = 1 ] && grep -q 'if \[ -f \${prefix}/themes/rudramos/theme.txt' '${CFG}'"
assert "keeps the GRUB password line" grep -q '^GRUB2_PASSWORD=grub.pbkdf2' "${CFG}"
run >/dev/null
assert "running again changes nothing (still one block)" bash -c "[ \"\$(grep -c '^### BEGIN RudramOS boot menu theme$' '${CFG}')\" = 1 ]"
echo "v2" >"${PCOS_GRUB_THEME_SRC}/.stamp"
echo "theme v2" >"${PCOS_GRUB_THEME_SRC}/theme.txt"
run >/dev/null
assert "a new image's theme replaces the old one" grep -q 'theme v2' "${PCOS_GRUB_DIR}/themes/rudramos/theme.txt"
assert "and still one block" bash -c "[ \"\$(grep -c '^### BEGIN RudramOS boot menu theme$' '${CFG}')\" = 1 ]"
assert "asks GRUB for a full-size screen first" grep -q '^  set gfxmode=1920x1080,.*,auto$' "${CFG}"
sed -i 's/^  set gfxmode=.*/  set gfxmode=auto/' "${CFG}"
run >/dev/null
assert "an old block is rewritten even when the theme files are unchanged" grep -q '^  set gfxmode=1920x1080' "${CFG}"
assert "and still one block after the rewrite" bash -c "[ \"\$(grep -c '^### BEGIN RudramOS boot menu theme$' '${CFG}')\" = 1 ]"
touch "${PCOS_NO_GRUB_THEME}"
run >/dev/null
assert "turning it off removes the block" bash -c "! grep -q 'RudramOS boot menu theme' '${CFG}'"
assert "and the theme files" bash -c "[ ! -e '${PCOS_GRUB_DIR}/themes/rudramos' ]"
assert "but keeps the GRUB password line" grep -q '^GRUB2_PASSWORD=grub.pbkdf2' "${CFG}"
assert "no /boot/grub2 at all: nothing to do" bash -c "PCOS_GRUB_DIR='${work}/missing' bash '${TOOL}'"

# Control Center switch: off / on
rm -f "${PCOS_NO_GRUB_THEME}"
bash "${TOOL}" >/dev/null
bash "${TOOL}" off >/dev/null
assert "off: flag set and theme removed" bash -c "[ -e '${PCOS_NO_GRUB_THEME}' ] && ! grep -q 'RudramOS boot menu theme' '${CFG}'"
bash "${TOOL}" on >/dev/null
assert "on: flag cleared and theme back" bash -c "[ ! -e '${PCOS_NO_GRUB_THEME}' ] && grep -q '^### BEGIN RudramOS boot menu theme$' '${CFG}'"
assert "unknown word refused" bash -c "bash '${TOOL}' maybe; [ \$? = 2 ]"

# Dual boot: a Windows entry in custom.cfg that GRUB shows only when it finds Windows
CUSTOM="${PCOS_GRUB_DIR}/custom.cfg"
WIN_COUNT="grep -c '^### BEGIN RudramOS Windows entry$' '${CUSTOM}'"
printf '%s\n' 'menuentry "My own entry" { true }' >"${CUSTOM}"
bash "${TOOL}" >/dev/null
assert "Windows entry added to custom.cfg" bash -c "[ \"\$(${WIN_COUNT})\" = 1 ]"
assert "it chainloads Windows' boot manager, found by GRUB" bash -c "grep -q 'search --no-floppy --file --set=root /EFI/Microsoft/Boot/bootmgfw.efi' '${CUSTOM}' && grep -q 'chainloader /EFI/Microsoft/Boot/bootmgfw.efi' '${CUSTOM}'"
assert "only on UEFI, only when found, then the menu waits 5 s" bash -c "grep -q 'grub_platform' '${CUSTOM}' && grep -q 'if search --no-floppy --file --set=pcos_windows' '${CUSTOM}' && grep -q 'set timeout=5' '${CUSTOM}'"
assert "no shell-only && or || (GRUB script)" bash -c "! sed -n '/RudramOS Windows entry/,/RudramOS Windows entry/p' '${CUSTOM}' | grep -qE '&&|\|\|'"
assert "the user's own custom.cfg entries are kept" grep -q 'My own entry' "${CUSTOM}"
bash "${TOOL}" >/dev/null
assert "running again: still one Windows block" bash -c "[ \"\$(${WIN_COUNT})\" = 1 ]"
bash "${TOOL}" windows-off >/dev/null
assert "windows-off removes it, keeps the rest" bash -c "[ \"\$(${WIN_COUNT})\" = 0 ] && grep -q 'My own entry' '${CUSTOM}'"
bash "${TOOL}" >/dev/null
assert "and it stays off at the next start" bash -c "[ \"\$(${WIN_COUNT})\" = 0 ]"
bash "${TOOL}" windows-on >/dev/null
assert "windows-on puts it back" bash -c "[ \"\$(${WIN_COUNT})\" = 1 ]"
bash "${TOOL}" off >/dev/null
assert "the Windows entry doesn't depend on the theme" bash -c "[ \"\$(${WIN_COUNT})\" = 1 ]"

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
