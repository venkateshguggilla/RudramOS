# RudramOS image
# Based on the Universal Blue image-template (Apache-2.0): https://github.com/ublue-os/image-template

# Base image and GPU variant (set by CI, see .github/workflows/build.yml):
#   pcos                 BASE_IMAGE=ghcr.io/ublue-os/bluefin              GPU=none
#   pcos-nvidia          BASE_IMAGE=ghcr.io/ublue-os/bluefin-nvidia-open  GPU=nvidia
#   pcos-nvidia-legacy   BASE_IMAGE=ghcr.io/ublue-os/bluefin              GPU=nvidia-legacy
ARG BASE_IMAGE="ghcr.io/ublue-os/bluefin"
ARG BASE_TAG="stable"

# Temp Monitor (https://github.com/venkateshguggilla/temp-monitor), built from a pinned
# commit so upstream changes only reach the OS when this ref is bumped. Unit tests must pass.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS temp-monitor
ARG TEMP_MONITOR_REF="bdd474e068c8230d1656a68e62b53e2a4110042b"
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

# Build scripts and system files are mounted at build time, not copied into the final image
FROM scratch AS ctx
COPY build_files /
COPY system_files /system_files
COPY keys /keys
COPY --from=temp-monitor /out /apps

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
