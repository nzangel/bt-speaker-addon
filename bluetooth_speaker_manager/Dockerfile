FROM ghcr.io/home-assistant/amd64-base:latest

ARG BUILD_ARCH=amd64
ARG BUILD_DATE
ARG BUILD_REF
ARG BUILD_VERSION

LABEL \
    io.hass.name="Bluetooth Speaker Manager" \
    io.hass.description="Connectez et gérez vos enceintes Bluetooth" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    maintainer="Christophe"

# Install dependencies
RUN apk add --no-cache \
    bluez \
    bluez-deprecated \
    bluez-libs \
    pulseaudio \
    pulseaudio-bluez \
    dbus \
    python3 \
    py3-pip \
    py3-dbus \
    py3-gobject3 \
    bash \
    curl \
    jq

# Install Python dependencies
RUN pip3 install --break-system-packages \
    fastapi \
    uvicorn \
    pydbus \
    httpx \
    aiofiles

# Copy application files
COPY rootfs /

# Make scripts executable
RUN chmod +x /usr/bin/bluetooth_manager.py \
    && chmod +x /run.sh

# Expose web interface port
EXPOSE 7880

CMD ["/run.sh"]
