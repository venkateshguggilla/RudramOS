#!/bin/bash
# Tests for system_files/usr/libexec/pcos/pcos-image-rename with stubbed bootc and skopeo.
# Run: bash tests/test-image-rename.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/libexec/pcos/pcos-image-rename"
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
case "$1" in
status) printf '{"spec":{"image":{"image":"%s","transport":"registry"}}}\n' "${SPEC}" ;;
switch) echo "$*" >"${SWITCHED}" ;;
esac
STUB
cat >"${work}/bin/skopeo" <<'STUB'
#!/bin/bash
[[ "${NEW_AVAILABLE:-1}" == 1 ]]
STUB
chmod +x "${work}/bin/bootc" "${work}/bin/skopeo"
export PATH="${work}/bin:${PATH}" SWITCHED="${work}/switched"

run() { rm -f "${SWITCHED}"; SPEC="$1" NEW_AVAILABLE="${2:-1}" bash "${TOOL}"; }

run "ghcr.io/venkateshguggilla/pcos-nvidia-legacy:latest" >/dev/null
assert "no in-place switch (it fails on a running PC: read-only /sysroot)" bash -c "! grep -q -- --mutate-in-place \"${SWITCHED}\""
assert "old legacy NVIDIA name moves to rudramos-nvidia-legacy" grep -q -- "--enforce-container-sigpolicy --transport registry ghcr.io/venkateshguggilla/rudramos-nvidia-legacy:latest" "${SWITCHED}"
run "ghcr.io/venkateshguggilla/pcos:latest" >/dev/null
assert "standard image moves to rudramos" grep -q "ghcr.io/venkateshguggilla/rudramos:latest" "${SWITCHED}"
run "ghcr.io/venkateshguggilla/pcos-nvidia:20261020" >/dev/null
assert "keeps the tag" grep -q "ghcr.io/venkateshguggilla/rudramos-nvidia:20261020" "${SWITCHED}"
run "ghcr.io/venkateshguggilla/pcos:latest" 0 >/dev/null
assert "waits while the new name can't be downloaded" test ! -e "${SWITCHED}"
run "ghcr.io/venkateshguggilla/rudramos:latest" >/dev/null
assert "already on the new name: nothing" test ! -e "${SWITCHED}"
run "ghcr.io/venkateshguggilla/pcos:unsigned-test" >/dev/null
assert "other tags of the old name move too" grep -q "rudramos:unsigned-test" "${SWITCHED}"
run "ghcr.io/someone-else/pcos:latest" >/dev/null
assert "a different image is left alone" test ! -e "${SWITCHED}"

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
