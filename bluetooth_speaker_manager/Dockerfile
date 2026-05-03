FROM ghcr.io/home-assistant/amd64-base:3.21

ARG BUILD_ARCH=amd64
ARG BUILD_DATE
ARG BUILD_REF
ARG BUILD_VERSION

# Install system dependencies
RUN apk add --no-cache \
    bluez \
    bluez-deprecated \
    bluez-libs \
    pulseaudio \
    pulseaudio-bluez \
    dbus \
    python3 \
    py3-pip \
    bash \
    curl \
    jq

# Install Python dependencies
RUN pip3 install --break-system-packages \
    fastapi \
    "uvicorn[standard]" \
    httpx \
    aiofiles

# Copy rootfs overlay (inclut etc/services.d/bluetooth_manager/run)
COPY rootfs /

# Rendre les scripts s6 et le manager exécutables
RUN chmod a+x \
    /etc/services.d/bluetooth_manager/run \
    /etc/services.d/bluetooth_manager/finish \
    /usr/bin/bluetooth_manager.py
