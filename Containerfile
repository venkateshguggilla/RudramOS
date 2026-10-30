# RudramOS image
# Based on the Universal Blue image-template (Apache-2.0): https://github.com/ublue-os/image-template

# Base image and GPU variant (set by CI, see .github/workflows/build.yml):
#   rudramos                 BASE_IMAGE=ghcr.io/ublue-os/bluefin              GPU=none
#   rudramos-nvidia          BASE_IMAGE=ghcr.io/ublue-os/bluefin-nvidia-open  GPU=nvidia
#   rudramos-nvidia-legacy   BASE_IMAGE=ghcr.io/ublue-os/bluefin              GPU=nvidia-legacy
ARG BASE_IMAGE="ghcr.io/ublue-os/bluefin"
ARG BASE_TAG="stable"

# Temp Monitor (https://github.com/venkateshguggilla/temp-monitor), built from a pinned
# commit so upstream changes only reach the OS when this ref is bumped. Unit tests must pass.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS temp-monitor
ARG TEMP_MONITOR_REF="189c5bdc63b7b7d0757bb211139ee511c3040d99"
WORKDIR /src
RUN git init -q . \
    && git fetch -q --depth 1 https://github.com/venkateshguggilla/temp-monitor.git "${TEMP_MONITOR_REF}" \
    && git checkout -q FETCH_HEAD
RUN dotnet test tests/TempMonitor.Core.Tests \
    && dotnet test tests/TempMonitor.Sensors.Linux.Tests \
    && dotnet test tests/TempMonitor.History.Tests \
    && dotnet publish src/TempMonitor.Avalonia -f net8.0 -r linux-x64 -c Release \
       -p:PublishSingleFile=false -o /out/temp-monitor \
    && cp src/TempMonitor.Avalonia/Assets/logo.png /out/temp-monitor.png \
    && cp -r packaging/linux /out/temp-monitor-packaging

# PC Cleaner (https://github.com/venkateshguggilla/pc-cleaner), a pinned commit. Python: fetched
# here, tested and installed by build.sh with the image's own Python and Tk.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS pc-cleaner
ARG PC_CLEANER_REF="0abe766468bb9b624bc2712f9dc9e44960dd8254"
WORKDIR /src
RUN git init -q . \
    && git fetch -q --depth 1 https://github.com/venkateshguggilla/pc-cleaner.git "${PC_CLEANER_REF}" \
    && git checkout -q FETCH_HEAD \
    && mkdir -p /out/pc-cleaner \
    && cp -r pccleaner tests assets packaging /out/pc-cleaner/

# scrcpy (https://github.com/Genymobile/scrcpy, Apache-2.0): its own Linux build, with the
# phone-side server and adb. "Phone Screen" / Control Center → Phone. Pinned by checksum.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS scrcpy
ARG SCRCPY_VERSION="5.0.1"
ARG SCRCPY_SHA256="9f969d30cc574816077edecda65719c1c70b0aee1df1ba5fa00779ac07b8fd6e"
WORKDIR /src
RUN curl -fsSLo scrcpy.tar.gz \
       "https://github.com/Genymobile/scrcpy/releases/download/v${SCRCPY_VERSION}/scrcpy-linux-x86_64-v${SCRCPY_VERSION}.tar.gz" \
    && echo "${SCRCPY_SHA256}  scrcpy.tar.gz" | sha256sum -c - \
    && mkdir -p /out/scrcpy \
    && tar xzf scrcpy.tar.gz --strip-components=1 -C /out/scrcpy

# LAN Share (https://github.com/venkateshguggilla/lan-share), a pinned commit: share files with
# PCs and phones on Home networks. Its tests must pass (the Electron ones under a virtual display).
FROM docker.io/library/node:22-bookworm AS lan-share
ARG LAN_SHARE_REF="5fce8c9630a84bc2a145f4cb5221c03bcdf71f03"
WORKDIR /src
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends xvfb xauth libnss3 libgtk-3-0 libgbm1 libasound2 >/dev/null \
    && rm -rf /var/lib/apt/lists/*
RUN git init -q . \
    && git fetch -q --depth 1 https://github.com/venkateshguggilla/lan-share.git "${LAN_SHARE_REF}" \
    && git checkout -q FETCH_HEAD
RUN npm ci --no-audit --no-fund \
    && npm run build \
    && node test/netprofile.test.js \
    && xvfb-run -a npx electron --no-sandbox test/e2e.js \
    && npx electron-builder --linux dir --x64 --publish never \
    && mkdir -p /out \
    && cp -a release/linux-unpacked /out/lan-share \
    && cp build/icon.png /out/lan-share.png

# Build scripts and system files are mounted at build time, not copied into the final image
FROM scratch AS ctx
COPY build_files /
COPY system_files /system_files
COPY keys /keys
COPY --from=temp-monitor /out /apps
COPY --from=pc-cleaner /out /apps
COPY --from=scrcpy /out /apps
COPY --from=lan-share /out /apps

FROM ${BASE_IMAGE}:${BASE_TAG}

ARG GPU="none"

### MODIFICATIONS
## All changes happen in build_files/build.sh (GPU drivers in build_files/gpu.sh)
RUN --mount=type=bind,from=ctx,source=/,target=/ctx \
    --mount=type=cache,dst=/var/cache \
    --mount=type=cache,dst=/var/log \
    --mount=type=tmpfs,dst=/tmp \
    GPU="${GPU}" /ctx/build.sh

### LINTING
## Verify final image and contents are correct
RUN bootc container lint
