#!/usr/bin/with-contenv bashio

LOG_LEVEL=$(bashio::config 'log_level' 'info')
AUTO_RECONNECT=$(bashio::config 'auto_reconnect' 'true')
RECONNECT_DELAY=$(bashio::config 'reconnect_delay' '30')

bashio::log.info "Démarrage du Bluetooth Speaker Manager..."

# D-Bus
if [ ! -f /run/dbus/pid ]; then
    mkdir -p /run/dbus
    dbus-daemon --system --fork || true
    bashio::log.info "D-Bus démarré"
fi

# Bluetooth adapter
rfkill unblock bluetooth 2>/dev/null || true
hciconfig hci0 up 2>/dev/null || true
bashio::log.info "Adaptateur Bluetooth activé"

# bluetoothd
if ! pgrep -x bluetoothd > /dev/null; then
    bluetoothd --nodetach &
    sleep 2
    bashio::log.info "bluetoothd démarré"
fi

# PulseAudio
mkdir -p /tmp/pulse
export PULSE_RUNTIME_PATH=/tmp/pulse

if ! pgrep -x pulseaudio > /dev/null; then
    pulseaudio \
        --system=false \
        --daemonize=false \
        --disallow-exit=true \
        --exit-idle-time=-1 &
    sleep 3
    pactl load-module module-bluetooth-discover 2>/dev/null || true
    pactl load-module module-bluetooth-policy 2>/dev/null || true
    bashio::log.info "PulseAudio démarré avec support Bluetooth"
fi

# Auto-reconnect background loop
if bashio::var.true "${AUTO_RECONNECT}"; then
    (
        while true; do
            sleep "${RECONNECT_DELAY}"
            if [ -f /data/trusted_devices.json ]; then
                DEVICES=$(jq -r '.[] | .address' /data/trusted_devices.json 2>/dev/null || echo "")
                for MAC in $DEVICES; do
                    if ! bluetoothctl info "$MAC" 2>/dev/null | grep -q "Connected: yes"; then
                        bashio::log.info "Reconnexion automatique de $MAC..."
                        bluetoothctl connect "$MAC" 2>/dev/null || true
                    fi
                done
            fi
        done
    ) &
    bashio::log.info "Auto-reconnexion activée (délai: ${RECONNECT_DELAY}s)"
fi

bashio::log.info "Démarrage de l'interface web sur le port 7880..."
exec python3 /usr/bin/bluetooth_manager.py
