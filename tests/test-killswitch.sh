#!/bin/bash
# Tests for system_files/usr/bin/pcos-killswitch with stubbed nmcli, getent, nft and systemctl.
# Run: bash tests/test-killswitch.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/bin/pcos-killswitch"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0
mkdir -p "${work}/bin"

cat >"${work}/bin/nmcli" <<'EOF'
#!/bin/bash
case "$*" in
"-t -f UUID,TYPE connection show")
    echo "aaaa:802-11-wireless"
    [[ -z "${NO_VPN:-}" ]] && { echo "wwww:wireguard"; echo "vvvv:wireguard"; } ;;
"-g connection.interface-name connection show wwww") echo "proton0" ;;
"-g connection.interface-name connection show vvvv")
    # EVIL: VPN settings a user can edit without admin approval, made to break out of the rules
    if [[ -n "${EVIL:-}" ]]; then echo 'x" } accept #'; else echo "wg-home"; fi ;;
"-g wireguard.peers connection show wwww") echo 'AbCd= endpoint=vpn.example.net:51820 allowed-ips=0.0.0.0/0;::/0' ;;
"-g wireguard.peers connection show vvvv")
    if [[ -n "${EVIL:-}" ]]; then echo 'EfGh= endpoint=[2001:db8::5]:99999 allowed-ips=10.8.0.0/24'
    else echo 'EfGh= endpoint=[2001:db8::5]:443 allowed-ips=10.8.0.0/24'; fi ;;
esac
EOF
cat >"${work}/bin/getent" <<'EOF'
#!/bin/bash
case "$2" in
vpn.example.net) printf '198.51.100.7    STREAM vpn.example.net\n198.51.100.7    DGRAM\n2001:db8::7     STREAM\n' ;;
2001:db8::5) printf '2001:db8::5     STREAM 2001:db8::5\n' ;;
esac
EOF
cat >"${work}/bin/nft" <<'EOF'
#!/bin/bash
echo "$*" >> "${NFT_LOG}"
case "$*" in
"list table inet pcos_killswitch") [[ -e "${NFT_STATE}" ]] ;;
"-f "*) touch "${NFT_STATE}" ;;
"delete table inet pcos_killswitch") rm -f "${NFT_STATE}" ;;
"-c -f "*) [[ -z "${NFT_REJECT:-}" ]] ;;
esac
EOF
printf '#!/bin/bash\necho "$*" >> "${SYSTEMCTL_LOG}"\n' >"${work}/bin/systemctl"
chmod +x "${work}/bin/"*

export PATH="${work}/bin:${PATH}" PCOS_ROOT="${work}" PCOS_TEST_ROOT=1
export NFT_LOG="${work}/nft.log" NFT_STATE="${work}/nft.state" SYSTEMCTL_LOG="${work}/systemctl.log"
RULES="${work}/etc/pcos/killswitch.nft"

assert() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}

assert "status off at start" bash -c "bash '${TOOL}' status | grep -q 'kill switch: off'"
assert "refused without a WireGuard VPN" bash -c "! NO_VPN=1 bash '${TOOL}' on"
assert "  nothing loaded" test ! -e "${NFT_STATE}"
assert "turn on" bash "${TOOL}" on
assert "  default policy drop" grep -q 'policy drop;' "${RULES}"
assert "  VPN interfaces allowed (incl. named ones)" grep -qF 'oifname { "wg*", "tun*", "proton0","wg-home" } accept' "${RULES}"
assert "  VPN server IPv4 + port allowed" grep -qF 'ip daddr { 198.51.100.7 } udp dport { 443,51820 } accept' "${RULES}"
assert "  VPN server IPv6 (bracketed endpoint) allowed" grep -qF 'ip6 daddr { 2001:db8::5,2001:db8::7 } udp dport { 443,51820 } accept' "${RULES}"
assert "  local network allowed" grep -qF 'ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16' "${RULES}"
assert "  IPv6 neighbour discovery allowed" grep -qF 'meta l4proto ipv6-icmp accept' "${RULES}"
assert "  rules checked before loading" grep -q '^-c -f ' "${NFT_LOG}"
assert "  loaded and boot service enabled" bash -c "[ -e '${NFT_STATE}' ] && grep -qx 'enable pcos-killswitch.service' '${SYSTEMCTL_LOG}'"
assert "status on" bash -c "bash '${TOOL}' status | grep -q 'kill switch: on'"
assert "turning on again replaces the table" bash -c "bash '${TOOL}' on && grep -c 'delete table inet pcos_killswitch' '${NFT_LOG}' | grep -q 1"
assert "rejected rules leave state unchanged" bash -c "cp '${RULES}' '${work}/before' && ! NFT_REJECT=1 bash '${TOOL}' on && cmp -s '${RULES}' '${work}/before'"
assert "turn off" bash -c "bash '${TOOL}' off && [ ! -e '${NFT_STATE}' ] && [ ! -e '${RULES}' ] && grep -qx 'disable pcos-killswitch.service' '${SYSTEMCTL_LOG}'"
# Security review: interface names and ports come from user-editable VPN settings
assert "on, with hostile VPN settings" bash -c "EVIL=1 bash '${TOOL}' on"
assert "  an interface name with rule syntax is left out" bash -c "! grep -qF 'x\"' '${RULES}' && grep -qF 'oifname { \"wg*\", \"tun*\", \"proton0\" } accept' '${RULES}'"
assert "  an out-of-range port is left out" bash -c "! grep -q 99999 '${RULES}' && grep -qF 'udp dport { 51820 } accept' '${RULES}'"
assert "  and its server isn't allowed either" bash -c "! grep -qF '2001:db8::5' '${RULES}'"
bash "${TOOL}" off >/dev/null 2>&1

assert "load with no saved rules does nothing" bash -c "bash '${TOOL}' load && [ ! -e '${NFT_STATE}' ]"
assert "not root refused" bash -c "! PCOS_TEST_ROOT=0 bash '${TOOL}' on"

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
