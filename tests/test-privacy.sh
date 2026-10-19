#!/bin/bash
# Tests for system_files/usr/bin/pcos-privacy (presets and generated config files).
# Run: bash tests/test-privacy.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/bin/pcos-privacy"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0
export PCOS_ROOT="${work}" PCOS_TEST_ROOT=1 PCOS_NO_RELOAD=1

NM="${work}/etc/NetworkManager/conf.d/60-pcos-privacy.conf"
DNS="${work}/etc/systemd/resolved.conf.d/80-pcos-dns.conf"
JOURNAL="${work}/etc/systemd/journald.conf.d/60-pcos-privacy.conf"
CLEAR="${work}/etc/pcos/firefox-policies.d/50-clear-on-exit.json"

assert() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}

assert "status defaults to balanced" bash -c "bash '${TOOL}' status | grep -q 'Privacy preset: balanced'"
assert "apply balanced" bash "${TOOL}" apply
assert "Wi-Fi MAC per network" grep -qx 'wifi.cloned-mac-address=stable' "${NM}"
assert "random MAC while scanning" grep -qx 'wifi.scan-rand-mac-address=yes' "${NM}"
assert "wired MAC unchanged in balanced" grep -qx 'ethernet.cloned-mac-address=permanent' "${NM}"
assert "hostname not sent" grep -qx 'ipv4.dhcp-send-hostname=false' "${NM}"
assert "IPv6 privacy addresses" grep -qx 'ipv6.ip6-privacy=2' "${NM}"
assert "network DNS not handed to resolved" bash -c "grep -qx 'dns=none' '${NM}' && grep -qx 'systemd-resolved=false' '${NM}'"
assert "captive-portal check on in balanced" grep -qx 'enabled=true' "${NM}"
assert "Quad9 over TLS, opportunistic" bash -c "grep -q '^DNS=9.9.9.9#dns.quad9.net' '${DNS}' && grep -qx 'DNSOverTLS=opportunistic' '${DNS}' && grep -qx 'Domains=~.' '${DNS}'"
assert "logs kept 14 days" grep -qx 'MaxRetentionSec=14day' "${JOURNAL}"
assert "no clear-on-exit in balanced" test ! -e "${CLEAR}"

assert "preset maximum" bash "${TOOL}" preset maximum
assert "  strict DNS-over-TLS" grep -qx 'DNSOverTLS=yes' "${DNS}"
assert "  tracker-blocking resolver (Mullvad base)" grep -q '^DNS=194.242.2.4#base.dns.mullvad.net 2a07:e340::4#base.dns.mullvad.net$' "${DNS}"
assert "  wired MAC per network" grep -qx 'ethernet.cloned-mac-address=stable' "${NM}"
assert "  captive-portal check off" grep -qx 'enabled=false' "${NM}"
assert "  logs kept 3 days" grep -qx 'MaxRetentionSec=3day' "${JOURNAL}"
assert "  Firefox clears on exit (valid JSON shape)" bash -c "grep -q '\"SanitizeOnShutdown\"' '${CLEAR}' && grep -q '\"Cookies\": true' '${CLEAR}'"
assert "  status says maximum" bash -c "bash '${TOOL}' status | grep -q 'Privacy preset: maximum'"

assert "set trackers off -> custom, back to Quad9 strict" bash -c "bash '${TOOL}' set trackers off && grep -q '^DNS=9.9.9.9' '${DNS}' && grep -qx 'DNSOverTLS=yes' '${DNS}' && bash '${TOOL}' status | grep -q 'preset: custom'"
assert "set dns cloudflare" bash -c "bash '${TOOL}' set dns cloudflare && grep -q '^DNS=1.1.1.1#cloudflare-dns.com' '${DNS}'"
assert "set dns mullvad (unfiltered)" bash -c "bash '${TOOL}' set dns mullvad && grep -q '^DNS=194.242.2.2#dns.mullvad.net' '${DNS}'"
assert "set clear_on_exit off removes policy" bash -c "bash '${TOOL}' set clear_on_exit off && [ ! -e '${CLEAR}' ]"
assert "set journal_days 30" bash -c "bash '${TOOL}' set journal_days 30 && grep -qx 'MaxRetentionSec=30day' '${JOURNAL}'"
assert "settings survive (saved state)" bash -c "bash '${TOOL}' status | grep -qE 'dns +mullvad' && bash '${TOOL}' status | grep -qE 'journal_days +30'"
assert "set trackers on, then dns network" bash -c "bash '${TOOL}' set trackers on && bash '${TOOL}' set dns network"
assert "  network DNS: no global servers, network DNS handed to resolved" bash -c "! grep -q '^DNS=' '${DNS}' && ! grep -q '^Domains=' '${DNS}' && ! grep -qx 'dns=none' '${NM}'"
assert "  network DNS wins over tracker blocking" bash -c "! grep -q 'mullvad' '${DNS}'"
assert "  MAC privacy still on" grep -qx 'wifi.cloned-mac-address=stable' "${NM}"
assert "back to quad9 restores encrypted-only DNS" bash -c "bash '${TOOL}' set trackers off && bash '${TOOL}' set dns quad9 && grep -q '^DNS=9.9.9.9' '${DNS}' && grep -qx 'dns=none' '${NM}'"
assert "invalid value refused" bash -c "! bash '${TOOL}' set dns google"
assert "journal_days out of range refused" bash -c "! bash '${TOOL}' set journal_days 0"
assert "unknown option refused" bash -c "! bash '${TOOL}' set telemetry on"
assert "preset balanced resets everything" bash -c "bash '${TOOL}' preset balanced && grep -q '^DNS=9.9.9.9' '${DNS}' && grep -qx 'DNSOverTLS=opportunistic' '${DNS}' && grep -qx 'MaxRetentionSec=14day' '${JOURNAL}'"
assert "not root refused" bash -c "! PCOS_TEST_ROOT=0 bash '${TOOL}' preset maximum"

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
