#!/bin/bash
# Tests for system_files/usr/bin/pcos-browser-extensions with a stubbed addons.mozilla.org.
# Run: bash tests/test-browser-extensions.sh   (needs jq)

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/bin/pcos-browser-extensions"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0

mkdir -p "${work}/bin"
cat >"${work}/bin/curl" <<'EOF'
#!/bin/bash
url="${@: -1}"
case "${url}" in
*/addon/bitwarden-password-manager/) echo '{"guid":"{446900e4-71c2-419f-a6a7-df9c091e268b}","name":{"en-US":"Bitwarden Password Manager"}}' ;;
*/addon/darkreader/) echo '{"guid":"addon@darkreader.org","name":"Dark Reader"}' ;;
*) exit 22 ;;
esac
EOF
chmod +x "${work}/bin/curl"

export PATH="${work}/bin:${PATH}" PCOS_TEST_ROOT=1
export BASE_POLICY="${ROOT}/system_files/usr/share/pcos/firefox/policies.base.json"
export APPROVED="${work}/etc/browser-extensions.json"
export FLATPAK_POLICY="${work}/flatpak/policies/policies.json"
export RPM_POLICY="${work}/etc-firefox/policies/policies.json"
export EXTRA_DIR="${work}/firefox-policies.d"

expect() {
    local desc="$1" want="$2"
    shift 2
    local out status
    out=$("$@" 2>&1)
    status=$?
    if [[ "${status}" == "${want}" ]]; then echo "ok   ${desc}"; else echo "FAIL ${desc}: exit ${status}, wanted ${want}. Output: ${out}"; failures=$((failures + 1)); fi
}
assert() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}
policy() { jq -e "$1" "${FLATPAK_POLICY}"; }

assert "base policy is valid JSON" jq -e '.policies.ExtensionSettings["*"].installation_mode == "blocked"' "${BASE_POLICY}"
expect "list with nothing approved" 0 bash "${TOOL}" list
expect "apply writes policies" 0 bash "${TOOL}" apply
assert "all extensions blocked by default" policy '.policies.ExtensionSettings["*"].installation_mode == "blocked"'
assert "uBlock Origin force-installed" policy '.policies.ExtensionSettings["uBlock0@raymondhill.net"].installation_mode == "force_installed"'
assert "RPM Firefox policy written too" cmp -s "${FLATPAK_POLICY}" "${RPM_POLICY}"

expect "approve by addons.mozilla.org link" 0 bash "${TOOL}" approve "https://addons.mozilla.org/en-US/firefox/addon/bitwarden-password-manager/?utm_source=x"
assert "Bitwarden auto-installs from AMO" policy '.policies.ExtensionSettings["{446900e4-71c2-419f-a6a7-df9c091e268b}"] == {"installation_mode":"normal_installed","install_url":"https://addons.mozilla.org/firefox/downloads/latest/bitwarden-password-manager/latest.xpi"}'
expect "approve by slug" 0 bash "${TOOL}" approve darkreader
assert "Dark Reader approved with its name" jq -e '.["addon@darkreader.org"].name == "Dark Reader"' "${APPROVED}"
expect "approve by id without url" 0 bash "${TOOL}" approve "example@extension.test"
assert "id-only approval is 'allowed'" policy '.policies.ExtensionSettings["example@extension.test"].installation_mode == "allowed"'
assert "still blocks everything else" policy '.policies.ExtensionSettings["*"].installation_mode == "blocked"'
# Security review: ids and install links typed by hand are checked
expect "approve by {uuid} id with an https link" 0 bash "${TOOL}" approve "{12345678-1234-1234-1234-123456789abc}" "https://example.org/ext.xpi"
expect "an id that isn't a Firefox extension id is refused" 1 bash "${TOOL}" approve 'a@b" bad'
expect "a plain-http install link is refused" 1 bash "${TOOL}" approve "other@extension.test" "http://example.org/ext.xpi"
expect "an install link with a space is refused" 1 bash "${TOOL}" approve "other@extension.test" "https://example.org/a b.xpi"
assert "refused ids weren't saved" jq -e 'has("other@extension.test") | not' "${APPROVED}"
expect "unknown AMO slug fails cleanly" 1 bash "${TOOL}" approve "https://addons.mozilla.org/firefox/addon/no-such-thing/"
expect "list shows approvals" 0 bash "${TOOL}" list
assert "list includes Bitwarden" bash -c "bash '${TOOL}' list | grep -q 'Bitwarden Password Manager'"

expect "revoke" 0 bash "${TOOL}" revoke "addon@darkreader.org"
assert "Dark Reader gone from policy" policy '.policies.ExtensionSettings | has("addon@darkreader.org") | not'
expect "revoke unknown fails" 1 bash "${TOOL}" revoke "addon@darkreader.org"
expect "not root refused" 1 env PCOS_TEST_ROOT=0 bash "${TOOL}" approve darkreader
mkdir -p "${EXTRA_DIR}"
printf '{"policies":{"SanitizeOnShutdown":{"Cookies":true}}}\n' >"${EXTRA_DIR}/50-clear-on-exit.json"
expect "apply with an extra policy file" 0 bash "${TOOL}" apply
assert "extra policy merged in" policy '.policies.SanitizeOnShutdown.Cookies == true'
assert "extensions still blocked after merge" policy '.policies.ExtensionSettings["*"].installation_mode == "blocked"'
assert "approved Bitwarden kept after merge" policy '.policies.ExtensionSettings | has("{446900e4-71c2-419f-a6a7-df9c091e268b}")'
printf 'not json' >"${EXTRA_DIR}/60-broken.json"
expect "broken extra policy file fails cleanly" 1 bash "${TOOL}" apply

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
