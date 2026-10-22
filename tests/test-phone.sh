#!/bin/bash
# Tests for system_files/usr/bin/pcos-phone with stubbed adb, scrcpy and notify-send.
# Run: bash tests/test-phone.sh

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${ROOT}/system_files/usr/bin/pcos-phone"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT
failures=0
mkdir -p "${work}/scrcpy" "${work}/bin"

assert() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then echo "ok   ${desc}"; else echo "FAIL ${desc}"; failures=$((failures + 1)); fi
}

cat >"${work}/scrcpy/adb" <<'STUB'
#!/bin/bash
echo "adb $*" >>"${CALLS}"
case "$1" in
devices) echo "List of devices attached"; cat "${DEVICES}" 2>/dev/null; echo ;;
connect) echo "${CONNECT_OUT:-connected to $2}" ;;
pair) echo "Successfully paired to $2" ;;
disconnect) echo "disconnected ${2:-everything}" ;;
esac
STUB
cat >"${work}/scrcpy/scrcpy" <<'STUB'
#!/bin/bash
echo "scrcpy $* server=${SCRCPY_SERVER_PATH} adb=${ADB}" >>"${CALLS}"
STUB
cat >"${work}/bin/notify-send" <<'STUB'
#!/bin/bash
echo "$*" >>"${NOTES}"
STUB
chmod +x "${work}/scrcpy/adb" "${work}/scrcpy/scrcpy" "${work}/bin/notify-send"
export PATH="${work}/bin:${PATH}" PCOS_SCRCPY_DIR="${work}/scrcpy"
export CALLS="${work}/calls" NOTES="${work}/notes" DEVICES="${work}/devices"
reset() { rm -f "${CALLS}" "${NOTES}" "${DEVICES}"; unset CONNECT_OUT; }

reset
printf '%s\n' \
    "R58M12345ABC           device usb:1-2 product:beyond1 model:SM_G973F device:beyond1 transport_id:1" \
    "192.168.1.20:41235     device product:panther model:Pixel_7 device:panther transport_id:2" >"${DEVICES}"
out=$(bash "${TOOL}" devices)
assert "lists a USB phone with its model" grep -qP '^R58M12345ABC\tdevice\tusb\tSM G973F$' <<<"${out}"
assert "lists a Wi-Fi phone" grep -qP '^192.168.1.20:41235\tdevice\twifi\tPixel 7$' <<<"${out}"
assert "no extra lines" test "$(wc -l <<<"${out}")" = 2

bash "${TOOL}" screen >/dev/null
assert "screen: opens the first phone, titled with its model" \
    grep -q -- "scrcpy --serial=R58M12345ABC --window-title=SM G973F --stay-awake" "${CALLS}"
assert "screen: uses the bundled server and adb" grep -q "server=${work}/scrcpy/scrcpy-server adb=${work}/scrcpy/adb" "${CALLS}"
reset
printf '%s\n' "192.168.1.20:41235     device product:panther model:Pixel_7 transport_id:2" \
    "R58M12345ABC           device usb:1-2 model:SM_G973F transport_id:1" >"${DEVICES}"
bash "${TOOL}" screen R58M12345ABC >/dev/null
assert "screen SERIAL: opens that phone" grep -q -- "--serial=R58M12345ABC" "${CALLS}"

reset
assert "screen with no phone: exit 3" bash -c "bash '${TOOL}' screen; [ \$? = 3 ]"
assert "and says how to connect one" grep -q "No phone found" "${NOTES}"
assert "and doesn't start scrcpy" bash -c "! grep -q scrcpy '${CALLS}'"

reset
echo "R58M12345ABC           unauthorized usb:1-2 transport_id:3" >"${DEVICES}"
assert "unauthorized phone: exit 3" bash -c "bash '${TOOL}' screen; [ \$? = 3 ]"
assert "and asks to tap Allow on the phone" grep -q "Tap Allow" "${NOTES}"
out=$(bash "${TOOL}" devices)
assert "unauthorized phone listed with a placeholder name" grep -qP '^R58M12345ABC\tunauthorized\tusb\tAndroid phone$' <<<"${out}"

reset
assert "pair with address and 6-digit code" bash "${TOOL}" pair 192.168.1.20:37099 123456
assert "runs adb pair" grep -q "adb pair 192.168.1.20:37099 123456" "${CALLS}"
assert "pair refuses a bad code" bash -c "bash '${TOOL}' pair 192.168.1.20:37099 12ab; [ \$? = 2 ]"
assert "pair refuses a bad address" bash -c "bash '${TOOL}' pair '1.2.3.4; rm -rf /:5' 123456; [ \$? = 2 ]"
assert "pair refuses a missing code" bash -c "bash '${TOOL}' pair 192.168.1.20:37099; [ \$? = 2 ]"
assert "connect succeeds" bash "${TOOL}" connect 192.168.1.20:41235
export CONNECT_OUT="failed to connect to '192.168.1.20:41235': Connection refused"
assert "connect reports adb's failure (adb itself exits 0)" bash -c "! bash '${TOOL}' connect 192.168.1.20:41235"
unset CONNECT_OUT
assert "disconnect one" bash "${TOOL}" disconnect 192.168.1.20:41235
assert "disconnect all" bash "${TOOL}" disconnect
assert "unknown command: usage" bash -c "bash '${TOOL}' frobnicate; [ \$? = 2 ]"

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
