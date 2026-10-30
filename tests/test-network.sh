#!/bin/bash
# Tests for system_files/usr/bin/pcos-network with stubbed nmcli, firewall-cmd and systemctl.
# Run: bash tests/test-network.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/bin/pcos-network"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0
mkdir -p "${work}/bin"

# Two active networks (Wi-Fi with a ':' in its name, wired) plus a VPN that must be ignored
cat >"${work}/bin/nmcli" <<'EOF'
#!/bin/bash
case "$*" in
"-t -f UUID,TYPE,DEVICE,NAME connection show --active")
    echo 'aaaa-1111:802-11-wireless:wlp2s0:Cafe\: Free WiFi'
    echo 'bbbb-2222:802-3-ethernet:enp3s0:Wired connection 1'
    echo 'cccc-3333:vpn:tun0:Work VPN' ;;
# pcos-network looks names up with "id" and real UUIDs with "uuid", never as a bare argument, so
# a name starting with "-" can't act as an nmcli option. The short test ids go through "id".
"-g connection.uuid,connection.id connection show id Wired connection 1"|"-g connection.uuid,connection.id connection show id bbbb-2222")
    printf 'bbbb-2222\nWired connection 1\n' ;;
"-g connection.uuid,connection.id connection show id aaaa-1111")
    printf 'aaaa-1111\nCafe: Free WiFi\n' ;;
"-g connection.uuid,connection.id connection show uuid 0b7c3a6e-1f2d-4c5b-9a8e-123456789abc")
    printf '0b7c3a6e-1f2d-4c5b-9a8e-123456789abc\nHome WiFi\n' ;;
"-g connection.uuid,connection.id connection show -"*) echo "nmcli was handed an option: $*" >&2; exit 99 ;;
"-g GENERAL.TYPE device show wlp2s0") echo wifi ;;
"-g GENERAL.TYPE device show enp3s0") echo ethernet ;;
"-g GENERAL.TYPE device show virbr0") echo bridge ;;
*) exit 10 ;;
esac
EOF
# firewall-cmd keeps the Home zone's permanent services in a file, logs zone changes
cat >"${work}/bin/firewall-cmd" <<'EOF'
#!/bin/bash
echo "$*" >> "${FW_LOG}"
case "$*" in
*--list-services*) cat "${FW_SERVICES}" 2>/dev/null | tr '\n' ' '; echo ;;
*--add-service=*) s="${*##*--add-service=}"; grep -qx "$s" "${FW_SERVICES}" 2>/dev/null || echo "$s" >> "${FW_SERVICES}" ;;
*--remove-service=*) s="${*##*--remove-service=}"; grep -vx "$s" "${FW_SERVICES}" > "${FW_SERVICES}.t" 2>/dev/null; mv "${FW_SERVICES}.t" "${FW_SERVICES}" ;;
esac
exit 0
EOF
cat >"${work}/bin/systemctl" <<'EOF'
#!/bin/bash
echo "$*" >> "${SYSTEMCTL_LOG}"
EOF
chmod +x "${work}/bin/"*

export PATH="${work}/bin:${PATH}" PCOS_TEST_ROOT=1
export TRUSTED_FILE="${work}/trusted-networks" FW_LOG="${work}/fw.log" FW_SERVICES="${work}/services" SYSTEMCTL_LOG="${work}/systemctl.log"

assert() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}
fw_has() { grep -qxF -- "$1" "${FW_LOG}"; }

assert "status works with nothing trusted" bash "${TOOL}" status
assert "status lists both networks as Public" bash -c "bash '${TOOL}' status | grep -q 'Cafe: Free WiFi (wlp2s0): Public' && bash '${TOOL}' status | grep -q 'Wired connection 1 (enp3s0): Public'"
assert "VPN not listed" bash -c "! bash '${TOOL}' status | grep -q 'Work VPN'"

: >"${FW_LOG}"
assert "apply puts every network in Public" bash "${TOOL}" apply
assert "  Wi-Fi -> pcos-public" fw_has "--zone=pcos-public --change-interface=wlp2s0"
assert "  wired -> pcos-public" fw_has "--zone=pcos-public --change-interface=enp3s0"
assert "  VPN untouched" bash -c "! grep -q tun0 '${FW_LOG}'"

: >"${FW_LOG}"
assert "trust wired as home (by name)" bash "${TOOL}" trust "Wired connection 1" home
assert "  recorded with UUID and name" grep -qxF $'bbbb-2222\tWired connection 1' "${TRUSTED_FILE}"
assert "  wired -> pcos-home" fw_has "--zone=pcos-home --change-interface=enp3s0"
assert "  Wi-Fi stays pcos-public" fw_has "--zone=pcos-public --change-interface=wlp2s0"
assert "  status shows Home" bash -c "bash '${TOOL}' status | grep -q 'Wired connection 1 (enp3s0): Home (trusted)'"
assert "trusting twice keeps one entry" bash -c "bash '${TOOL}' trust bbbb-2222 home && [ \$(grep -c bbbb-2222 '${TRUSTED_FILE}') -eq 1 ]"
assert "unknown network refused" bash -c "! bash '${TOOL}' trust 'Nope' home"
assert "a real UUID is looked up as a UUID" bash -c "bash '${TOOL}' trust 0b7c3a6e-1f2d-4c5b-9a8e-123456789abc home && grep -q '^0b7c3a6e-1f2d-4c5b-9a8e-123456789abc' '${TRUSTED_FILE}'"
assert "a name starting with '-' is looked up as a name, not passed as an option" bash -c "bash '${TOOL}' trust --active home 2>&1 | grep -q 'No such network: --active'"
assert "bad trust level refused" bash -c "! bash '${TOOL}' trust bbbb-2222 trusted"

: >"${FW_LOG}"
assert "apply-device for Wi-Fi uses its trust" bash -c "bash '${TOOL}' apply-device wlp2s0 aaaa-1111 && grep -qxF -- '--zone=pcos-public --change-interface=wlp2s0' '${FW_LOG}'"
assert "apply-device ignores bridges" bash -c "bash '${TOOL}' apply-device virbr0 zzzz && ! grep -q virbr0 '${FW_LOG}'"

assert "share phone on" bash "${TOOL}" share phone on
assert "  kdeconnect added to Home zone only" bash -c "grep -qxF -- '--permanent --zone=pcos-home --add-service=kdeconnect' '${FW_LOG}' && ! grep -q 'pcos-public --add-service' '${FW_LOG}'"
assert "share ssh on starts sshd" bash -c "bash '${TOOL}' share ssh on && grep -qx 'enable --now sshd.service' '${SYSTEMCTL_LOG}'"
assert "status shows shared services" bash -c "bash '${TOOL}' status | grep -q 'phone: on' && bash '${TOOL}' status | grep -q 'ssh: on'"
assert "unknown service refused" bash -c "! bash '${TOOL}' share telnet on"
assert "share phone off" bash -c "bash '${TOOL}' share phone off && ! grep -qx kdeconnect '${FW_SERVICES}'"
assert "stop-sharing closes everything and stops sshd" bash -c "bash '${TOOL}' stop-sharing && [ ! -s '${FW_SERVICES}' ] && grep -qx 'disable --now sshd.service' '${SYSTEMCTL_LOG}'"
assert "status: nothing shared" bash -c "bash '${TOOL}' status | grep -q 'nothing shared'"

assert "trust back to public removes entry" bash -c "bash '${TOOL}' trust bbbb-2222 public && ! grep -q bbbb-2222 '${TRUSTED_FILE}'"
assert "not root refused" bash -c "! PCOS_TEST_ROOT=0 bash '${TOOL}' trust bbbb-2222 home"

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
