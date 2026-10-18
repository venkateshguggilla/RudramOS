#!/bin/bash
# GPU driver layer for the PC OS image variants. Called from build.sh with GPU set.
#   none           AMD/Intel: open drivers already in the base image
#   nvidia         NVIDIA latest (open kernel modules): already in the bluefin-nvidia-open base
#   nvidia-legacy  NVIDIA 580 LTS (closed kernel modules) for GTX 10 series and older:
#                  installed here from Universal Blue's prebuilt akmods-nvidia-lts image

set -ouex pipefail

case "${GPU}" in
none)
    echo "GPU=none: using the base image's open drivers"
    ;;
nvidia)
    # Fail early if the base image isn't actually an NVIDIA one
    rpm -q kmod-nvidia nvidia-driver
    ;;
nvidia-legacy)
    FEDORA="$(rpm -E %fedora)"
    KERNEL="$(rpm -q kernel --queryformat '%{VERSION}-%{RELEASE}.%{ARCH}\n' | tail -n1)"
    AKMODS_REF="docker://ghcr.io/ublue-os/akmods-nvidia-lts:coreos-stable-${FEDORA}-${KERNEL}"

    command -v skopeo >/dev/null || dnf5 install -y skopeo
    if ! skopeo inspect --retry-times 3 "${AKMODS_REF}" >/dev/null; then
        echo "ERROR: no NVIDIA LTS kmods published for kernel ${KERNEL} yet (${AKMODS_REF})." >&2
        echo "Universal Blue usually publishes them within a day of a kernel update; re-run the build later." >&2
        exit 1
    fi

    # Same steps Bluefin uses for its NVIDIA images (03-install-kernel-akmods.sh),
    # with the LTS (580) kmods instead of nvidia-open
    skopeo copy --retry-times 3 "${AKMODS_REF}" dir:/tmp/akmods-rpms
    NVIDIA_TARGZ=$(jq -r '.layers[].digest' </tmp/akmods-rpms/manifest.json | cut -d : -f 2)
    tar -xzf /tmp/akmods-rpms/"${NVIDIA_TARGZ}" -C /tmp/
    mv /tmp/rpms/* /tmp/akmods-rpms/

    dnf5 config-manager setopt excludepkgs=golang-github-nvidia-container-toolkit
    IMAGE_NAME="silverblue" AKMODNV_PATH="/tmp/akmods-rpms" MULTILIB=0 \
        /tmp/akmods-rpms/ublue-os/nvidia-install.sh

    rm -f /usr/share/vulkan/icd.d/nouveau_icd.*.json
    ln -sf libnvidia-ml.so.1 /usr/lib64/libnvidia-ml.so
    mkdir -p /usr/lib/bootc/kargs.d
    tee /usr/lib/bootc/kargs.d/00-nvidia.toml <<EOF
kargs = ["rd.driver.blacklist=nouveau", "modprobe.blacklist=nouveau", "nvidia-drm.modeset=1", "initcall_blacklist=simpledrm_platform_driver_init"]
EOF

    # Check we got the 580 branch with closed modules
    DRIVER_VERSION="$(rpm -q --queryformat '%{VERSION}' nvidia-driver)"
    [[ "${DRIVER_VERSION}" == 580.* ]] || { echo "ERROR: expected NVIDIA 580.x, got ${DRIVER_VERSION}" >&2; exit 1; }

    # Rebuild the initramfs so it includes the NVIDIA modules (as Bluefin does for its
    # NVIDIA images). simpledrm is disabled by the kargs above, so without this the
    # boot-time disk unlock screen would have no display driver.
    export DRACUT_NO_XATTR=1
    dracut --no-hostonly --kver "${KERNEL}" --reproducible -v --add ostree -f "/lib/modules/${KERNEL}/initramfs.img"
    chmod 0600 "/lib/modules/${KERNEL}/initramfs.img"
    lsinitrd "/lib/modules/${KERNEL}/initramfs.img" | grep -E "nvidia(-drm)?\.ko" || { echo "ERROR: NVIDIA modules missing from initramfs" >&2; exit 1; }
    ;;
*)
    echo "ERROR: unknown GPU variant '${GPU}'" >&2
    exit 1
    ;;
esac

echo "${GPU}" > /usr/share/pcos/gpu-variant
