#!/bin/bash
# Tests for system_files/usr/libexec/pcos/pcos-usb-describe (USB kinds and BadUSB warnings).
# Run: bash tests/test-usb-describe.sh

set -uo pipefail
TOOL="$(cd "$(dirname "$0")/.." && pwd)/system_files/usr/libexec/pcos/pcos-usb-describe"
failures=0

check() {
    local desc="$1" want_kind="$2" want_level="$3" rule="$4" out kind level
    out=$(bash "${TOOL}" "${rule}")
    kind=$(cut -f1 <<<"${out}")
    level=$(cut -f3 <<<"${out}")
    if [[ "${kind}" == "${want_kind}" && "${level}" == "${want_level}" ]]; then
        echo "ok   ${desc}: ${kind} (${level})"
    else
        echo "FAIL ${desc}: got '${kind}' (${level}), wanted '${want_kind}' (${want_level})"
        failures=$((failures + 1))
    fi
}

check "USB stick" "Storage" ok \
    'block id 0781:5581 serial "4C530001" name "Ultra" hash "abc" parent-hash "def" via-port "2-1" with-interface 08:06:50 with-connect-type "hotplug"'
check "keyboard" "Keyboard" caution \
    'block id 046d:c31c serial "" name "USB Keyboard" hash "x" parent-hash "y" with-interface { 03:01:01 03:00:00 } with-connect-type "hotplug"'
check "mouse" "Mouse" ok \
    'block id 046d:c077 serial "" name "USB Optical Mouse" hash "x" parent-hash "y" with-interface 03:01:02 with-connect-type "hotplug"'
check "keyboard + mouse receiver" "Keyboard + Mouse" caution \
    'block id 046d:c52b serial "" name "USB Receiver" hash "x" parent-hash "y" with-interface { 03:01:01 03:01:02 03:00:00 } with-connect-type "hotplug"'
check "BadUSB: storage that types" "Keyboard + Storage" danger \
    'block id 1b4f:9206 serial "" name "Flash Disk" hash "x" parent-hash "y" with-interface { 08:06:50 03:01:01 } with-connect-type "hotplug"'
check "YubiKey 5 (keyboard + FIDO + CCID)" "Security key" ok \
    'block id 1050:0407 serial "" name "YubiKey OTP+FIDO+CCID" hash "x" parent-hash "y" with-interface { 03:01:01 03:00:00 0b:00:00 } with-connect-type "hotplug"'
check "FIDO-only key (Google Titan style)" "Security key" ok \
    'block id 18d1:5026 serial "" name "Titan Security Key" hash "x" parent-hash "y" with-interface 03:00:00 with-connect-type "hotplug"'
# Security review: a vendor id is easy to fake, so the interfaces must fit a security key too
check "fake 'YubiKey' that is a keyboard + storage" "Keyboard + Storage" danger \
    'block id 1050:0407 serial "" name "YubiKey OTP+FIDO+CCID" hash "x" parent-hash "y" with-interface { 03:01:01 08:06:50 } with-connect-type "hotplug"'
check "fake 'YubiKey' that is a network adapter" "Network adapter" danger \
    'block id 1050:0407 serial "" name "YubiKey" hash "x" parent-hash "y" with-interface { 02:06:00 0a:00:00 } with-connect-type "hotplug"'
check "security-key maker id without any interfaces" "Unknown device" danger \
    'block id 1050:0407 serial "" name "YubiKey" hash "x" parent-hash "y"'
msg=$(bash "${TOOL}" 'block id 1050:0407 serial "" name "YubiKey" with-interface { 03:01:01 08:06:50 }' | cut -f4)
if [[ "${msg}" == *"claims to be a security key"* ]]; then echo "ok   disguise explained"; else echo "FAIL disguise message: ${msg}"; failures=$((failures + 1)); fi
check "phone tethering (RNDIS)" "Network adapter" caution \
    'block id 18d1:4ee3 serial "ABC" name "Pixel 8" hash "x" parent-hash "y" with-interface { e0:01:03 0a:00:00 } with-connect-type "hotplug"'
check "storage that is also a network adapter" "Storage + Network adapter" danger \
    'block id 1234:5678 serial "" name "Mass Storage" hash "x" parent-hash "y" with-interface { 08:06:50 02:06:00 0a:00:00 } with-connect-type "hotplug"'
check "webcam with mic" "Audio + Camera" ok \
    'block id 046d:085c serial "" name "C922 Pro Stream Webcam" hash "x" parent-hash "y" with-interface { 0e:01:00 0e:02:00 01:01:00 01:02:00 } with-connect-type "hotplug"'
check "hub" "Hub" ok \
    'block id 05e3:0610 serial "" name "USB2.1 Hub" hash "x" parent-hash "y" with-interface 09:00:00 with-connect-type "hotplug"'
check "phone file transfer (MTP)" "Camera/phone (photos)" ok \
    'block id 04e8:6860 serial "R58N" name "SAMSUNG_Android" hash "x" parent-hash "y" with-interface 06:01:01 with-connect-type "hotplug"'
check "vendor-specific only" "Special device (vendor-specific)" ok \
    'block id 0bda:8179 serial "" name "802.11n NIC" hash "x" parent-hash "y" with-interface ff:ff:ff with-connect-type "hotplug"'
check "game controller" "Input device" ok \
    'block id 045e:028e serial "" name "Controller" hash "x" parent-hash "y" with-interface { ff:5d:01 03:00:00 } with-connect-type "hotplug"'

name=$(bash "${TOOL}" 'block id 0781:5581 serial "" name "Ultra Fit" with-interface 08:06:50' | cut -f2)
if [[ "${name}" == "Ultra Fit" ]]; then echo "ok   name extracted"; else echo "FAIL name: ${name}"; failures=$((failures + 1)); fi
name=$(bash "${TOOL}" 'block id 0781:5581 serial "" name "" with-interface 08:06:50' | cut -f2)
if [[ "${name}" == "USB device 0781:5581" ]]; then echo "ok   fallback name"; else echo "FAIL fallback name: ${name}"; failures=$((failures + 1)); fi

echo
if (( failures > 0 )); then echo "${failures} test(s) failed"; exit 1; fi
echo "all tests passed"
