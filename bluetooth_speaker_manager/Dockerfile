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

# Copy rootfs overlay
COPY rootfs /

# Make scripts executable
RUN chmod a+x /usr/bin/bluetooth_manager.py \
    && chmod a+x /run.sh

EXPOSE 7880

CMD ["/run.sh"]
