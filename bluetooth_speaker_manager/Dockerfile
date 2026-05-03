ARG BUILD_FROM
FROM ${BUILD_FROM}

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
    mpd \
    mpc \
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
