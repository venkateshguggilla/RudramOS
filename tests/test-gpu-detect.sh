#!/bin/bash
# Tests for system_files/usr/libexec/pcos/pcos-gpu-detect using sample lspci -Dnnmm output.
# Run: bash tests/test-gpu-detect.sh

set -uo pipefail
DETECT="$(dirname "$0")/../system_files/usr/libexec/pcos/pcos-gpu-detect"
failures=0

check() {
    local desc="$1" expected="$2" input="$3"
    local got
    got=$(PCOS_LSPCI_OUTPUT="${input}" bash "${DETECT}" | cut -f1)
    if [[ "${got}" == "${expected}" ]]; then
        echo "ok   ${desc} -> ${got}"
    else
        echo "FAIL ${desc}: expected ${expected}, got ${got}"
        failures=$((failures + 1))
    fi
}

HOST_BRIDGE='0000:00:00.0 "Host bridge [0600]" "Intel Corporation [8086]" "8th Gen Core Processor Host Bridge/DRAM Registers [3ec4]" "Apple Inc. [106b]" "Device [0000]"'

check "RTX 3060" pcos-nvidia "${HOST_BRIDGE}
0000:01:00.0 \"VGA compatible controller [0300]\" \"NVIDIA Corporation [10de]\" \"GA106 [GeForce RTX 3060 Lite Hash Rate] [2504]\" -ra1 \"ASUSTeK Computer Inc. [1043]\" \"Device [8814]\"
0000:01:00.1 \"Audio device [0403]\" \"NVIDIA Corporation [10de]\" \"GA106 High Definition Audio Controller [228e]\" -ra1 \"ASUSTeK Computer Inc. [1043]\" \"Device [8814]\""

check "GTX 1050 Ti" pcos-nvidia-legacy "0000:01:00.0 \"VGA compatible controller [0300]\" \"NVIDIA Corporation [10de]\" \"GP107 [GeForce GTX 1050 Ti] [1c82]\" -ra1 \"Micro-Star International Co., Ltd. [MSI] [1462]\" \"Device [8c96]\""

check "GTX 1080 (4-hex name in brackets)" pcos-nvidia-legacy "0000:01:00.0 \"VGA compatible controller [0300]\" \"NVIDIA Corporation [10de]\" \"GP104 [GeForce GTX 1080] [1b80]\" -ra1 \"NVIDIA Corporation [10de]\" \"Device [119e]\""

check "GTX 1650 (Turing, open modules)" pcos-nvidia "0000:01:00.0 \"VGA compatible controller [0300]\" \"NVIDIA Corporation [10de]\" \"TU117 [GeForce GTX 1650] [1f82]\" -ra1 \"Gigabyte Technology Co., Ltd [1458]\" \"Device [3fcb]\""

check "GTX 750 Ti (Maxwell)" pcos-nvidia-legacy "0000:01:00.0 \"VGA compatible controller [0300]\" \"NVIDIA Corporation [10de]\" \"GM107 [GeForce GTX 750 Ti] [1380]\" -ra2 \"Device [0000]\" \"Device [0000]\""

check "GTX 680 (Kepler, unsupported)" pcos "0000:01:00.0 \"VGA compatible controller [0300]\" \"NVIDIA Corporation [10de]\" \"GK104 [GeForce GTX 680] [1180]\" -ra1 \"Device [0000]\" \"Device [0000]\""

check "Intel iGPU + NVIDIA laptop dGPU (3D controller)" pcos-nvidia "0000:00:02.0 \"VGA compatible controller [0300]\" \"Intel Corporation [8086]\" \"Alder Lake-P GT2 [Iris Xe Graphics] [46a6]\" -r0c \"Lenovo [17aa]\" \"Device [3a4f]\"
0000:01:00.0 \"3D controller [0302]\" \"NVIDIA Corporation [10de]\" \"GA107M [GeForce RTX 3050 Mobile] [25a2]\" -ra1 \"Lenovo [17aa]\" \"Device [3a4f]\""

check "MacBook Pro 16 (AMD 5500M)" pcos "${HOST_BRIDGE}
0000:03:00.0 \"VGA compatible controller [0300]\" \"Advanced Micro Devices, Inc. [AMD/ATI] [1002]\" \"Navi 14 [Radeon Pro 5300M / 5500M] [7340]\" \"Apple Inc. [106b]\" \"Device [0210]\""

check "Hyper-V VM (no PCI display device)" pcos "${HOST_BRIDGE}"

check "NVIDIA audio function only is ignored" pcos "0000:01:00.1 \"Audio device [0403]\" \"NVIDIA Corporation [10de]\" \"GA106 High Definition Audio Controller [228e]\" -ra1 \"Device [0000]\" \"Device [0000]\""

echo
if (( failures > 0 )); then
    echo "${failures} test(s) failed"
    exit 1
fi
echo "all tests passed"
