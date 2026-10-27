#!/bin/bash
# Tests for system_files/usr/bin/pcos-admin-mode with stubbed pamu2fcfg, pamtester and id.
# Run: bash tests/test-admin-mode.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/bin/pcos-admin-mode"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0

mkdir -p "${work}/bin" "${work}/pam.d" "${work}/etc"
# Stubs: a fake key returns a new credential each call; pamtester passes unless PAMTESTER_FAIL=1
cat >"${work}/bin/pamu2fcfg" <<'EOF'
#!/bin/bash
n=$(( $(cat "${STUB_COUNTER}" 2>/dev/null || echo 0) + 1 )); echo "$n" > "${STUB_COUNTER}"
user=""; while [[ $# -gt 0 ]]; do [[ "$1" == "-u" ]] && user="$2"; shift; done
echo "${user}:KH${n},PK${n},es256,+presence"
EOF
cat >"${work}/bin/pamtester" <<'EOF'
#!/bin/bash
[[ -f "${PAM_DIR}/$1" ]] || { echo "service $1 missing" >&2; exit 2; }
[[ "${PAMTESTER_FAIL:-0}" == 1 ]] && exit 1
exit 0
EOF
cat >"${work}/bin/id" <<'EOF'
#!/bin/bash
if [[ "$1" == -nu ]]; then [[ "$2" == 1000 ]] && echo venky; exit; fi
[[ "$1" == "venky" || "$1" == "guest" ]]
EOF
chmod +x "${work}/bin/"*

export PATH="${work}/bin:${PATH}" PCOS_TEST_ROOT=1 SUDO_USER=venky
export PAM_DIR="${work}/pam.d" TEMPLATE_DIR="${ROOT}/system_files/usr/share/pcos/pam"
export U2F_MAPPINGS="${work}/etc/u2f_mappings" MODE_FILE="${work}/etc/admin-mode"
export STUB_COUNTER="${work}/counter"
cp "${TEMPLATE_DIR}/pcos-admin.standard" "${PAM_DIR}/pcos-admin"
: >"${U2F_MAPPINGS}"

expect() {
    local desc="$1" want_status="$2"
    shift 2
    local out status
    out=$("$@" 2>&1)
    status=$?
    if [[ "${status}" == "${want_status}" ]]; then
        echo "ok   ${desc}"
    else
        echo "FAIL ${desc}: exit ${status}, wanted ${want_status}. Output: ${out}"
        failures=$((failures + 1))
    fi
}
assert() {
    local desc="$1"
    shift
    if "$@"; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}

expect "status works in standard mode" 0 bash "${TOOL}" status
expect "strong refused without a key" 1 bash "${TOOL}" strong
assert "still standard after refusal" grep -qx standard <(cat "${MODE_FILE}" 2>/dev/null || echo standard)

expect "add first key" 0 bash "${TOOL}" add-key
expect "add backup key" 0 bash "${TOOL}" add-key
assert "two keys on one line" grep -qx 'venky:KH1,PK1,es256,+presence:KH2,PK2,es256,+presence' "${U2F_MAPPINGS}"
expect "add key for another user" 0 bash "${TOOL}" add-key guest
assert "other user on its own line" grep -qx 'guest:KH3,PK3,es256,+presence' "${U2F_MAPPINGS}"
expect "unknown user refused" 1 bash "${TOOL}" add-key nobody

PAMTESTER_FAIL=1 expect "strong refused when the test fails" 1 bash "${TOOL}" strong
assert "pcos-admin still standard" grep -q 'include      system-auth' "${PAM_DIR}/pcos-admin"
assert "temporary test service cleaned up" bash -c "! ls '${PAM_DIR}' | grep -q pcos-admin-test"

expect "strong enabled after passing test" 0 bash "${TOOL}" strong
assert "pcos-admin uses pam_u2f" grep -q 'pam_u2f.so authfile=' "${PAM_DIR}/pcos-admin"
assert "mode file says strong" grep -qx strong "${MODE_FILE}"
expect "removing own keys refused in strong mode" 1 bash "${TOOL}" remove-keys
expect "removing another user's keys allowed" 0 bash "${TOOL}" remove-keys guest
assert "guest keys gone, venky kept" bash -c "! grep -q '^guest:' '${U2F_MAPPINGS}' && grep -q '^venky:' '${U2F_MAPPINGS}'"

# Control Center runs it through pkexec: no SUDO_USER, the caller is PKEXEC_UID
expect "pkexec: removing own keys refused in strong mode" 1 env -u SUDO_USER PKEXEC_UID=1000 bash "${TOOL}" remove-keys
expect "pkexec: add-key for the caller" 0 env -u SUDO_USER PKEXEC_UID=1000 bash "${TOOL}" add-key
assert "pkexec: key added to the caller's line" grep -q '^venky:.*:KH' "${U2F_MAPPINGS}"
expect "no caller at all refused" 1 env -u SUDO_USER -u PKEXEC_UID bash "${TOOL}" add-key

expect "back to standard" 0 bash "${TOOL}" standard
assert "pcos-admin is standard template" cmp -s "${PAM_DIR}/pcos-admin" "${TEMPLATE_DIR}/pcos-admin.standard"
expect "not root refused" 1 env PCOS_TEST_ROOT=0 bash "${TOOL}" standard

echo
if (( failures > 0 )); then
    echo "${failures} test(s) failed"
    exit 1
fi
echo "all tests passed"
