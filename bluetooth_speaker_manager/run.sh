#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json

LOG_LEVEL=$(jq --raw-output '.log_level // "info"' $CONFIG_PATH)
AUTO_RECONNECT=$(jq --raw-output '.auto_reconnect // true' $CONFIG_PATH)
RECONNECT_DELAY=$(jq --raw-output '.reconnect_delay // 30' $CONFIG_PATH)

echo "[bt-manager] Démarrage du Bluetooth Speaker Manager..."

# Start D-Bus if not running
if [ ! -f /run/dbus/pid ]; then
    mkdir -p /run/dbus
    dbus-daemon --system --fork
    echo "[bt-manager] D-Bus démarré"
fi

# Enable Bluetooth adapter
rfkill unblock bluetooth 2>/dev/null || true
hciconfig hci0 up 2>/dev/null || true
echo "[bt-manager] Adaptateur Bluetooth activé"

# Start bluetoothd
if ! pgrep -x bluetoothd > /dev/null; then
    bluetoothd --nodetach &
    sleep 2
    echo "[bt-manager] bluetoothd démarré"
fi

# Configure PulseAudio for Bluetooth (A2DP)
mkdir -p /tmp/pulse
export PULSE_RUNTIME_PATH=/tmp/pulse

if ! pgrep -x pulseaudio > /dev/null; then
    pulseaudio \
        --system=false \
        --daemonize=false \
        --disallow-exit=true \
        --exit-idle-time=-1 \
        --log-level=${LOG_LEVEL} &
    sleep 3
    
    # Load Bluetooth modules
    pactl load-module module-bluetooth-discover 2>/dev/null || true
    pactl load-module module-bluetooth-policy 2>/dev/null || true
    echo "[bt-manager] PulseAudio démarré avec support Bluetooth"
fi

# Auto-reconnect loop (background)
if [ "$AUTO_RECONNECT" = "true" ]; then
    (
        while true; do
            sleep ${RECONNECT_DELAY}
            if [ -f /data/trusted_devices.json ]; then
                DEVICES=$(jq -r '.[] | .address' /data/trusted_devices.json 2>/dev/null || echo "")
                for MAC in $DEVICES; do
                    STATUS=$(bluetoothctl info "$MAC" 2>/dev/null | grep "Connected: yes" || echo "")
                    if [ -z "$STATUS" ]; then
                        echo "[bt-manager] Reconnexion automatique de $MAC..."
                        bluetoothctl connect "$MAC" 2>/dev/null || true
                    fi
                done
            fi
        done
    ) &
    echo "[bt-manager] Auto-reconnexion activée (délai: ${RECONNECT_DELAY}s)"
fi

# Start the web manager API
echo "[bt-manager] Démarrage de l'interface web sur le port 7880..."
exec python3 /usr/bin/bluetooth_manager.py
