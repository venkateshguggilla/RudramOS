# PC OS image
# Based on the Universal Blue image-template (Apache-2.0): https://github.com/ublue-os/image-template

# Build scripts and system files are mounted at build time, not copied into the final image
FROM scratch AS ctx
COPY build_files /
COPY system_files /system_files
COPY keys /keys

# Base image: Bluefin (GNOME, Fedora atomic). See docs/DESIGN.md §2.3.
# Phase 2 adds GPU variants:
#   ghcr.io/ublue-os/bluefin-nvidia-open:stable   (RTX 20 series and newer)
#   own 580xx legacy build                        (GTX 10 series)
FROM ghcr.io/ublue-os/bluefin:stable

### MODIFICATIONS
## All changes happen in build_files/build.sh
RUN --mount=type=bind,from=ctx,source=/,target=/ctx \
    --mount=type=cache,dst=/var/cache \
    --mount=type=cache,dst=/var/log \
    --mount=type=tmpfs,dst=/tmp \
    /ctx/build.sh

### LINTING
## Verify final image and contents are correct
RUN bootc container lint
