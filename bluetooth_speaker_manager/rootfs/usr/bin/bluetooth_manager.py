#!/usr/bin/env python3
"""
Bluetooth Speaker Manager - Backend FastAPI + Interface Web intégrée
Home Assistant Add-on
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─── Config ───────────────────────────────────────────────────────────────────

CONFIG_PATH = Path("/data/options.json")
DEVICES_PATH = Path("/data/trusted_devices.json")
LOG_LEVEL = "info"

try:
    with open(CONFIG_PATH) as f:
        config = json.load(f)
        LOG_LEVEL = config.get("log_level", "info")
        SCAN_TIMEOUT = config.get("scan_timeout", 15)
except Exception:
    SCAN_TIMEOUT = 15

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("bt-manager")

# ─── Persistent device store ──────────────────────────────────────────────────

def load_trusted_devices() -> list:
    if DEVICES_PATH.exists():
        try:
            return json.loads(DEVICES_PATH.read_text())
        except Exception:
            return []
    return []


def save_trusted_devices(devices: list):
    DEVICES_PATH.write_text(json.dumps(devices, indent=2))


# ─── Bluetooth helpers ────────────────────────────────────────────────────────

def run_bluetoothctl(*cmds: str, timeout: int = 10) -> str:
    """Run one or more bluetoothctl commands and return combined output."""
    input_str = "\n".join(list(cmds) + ["quit\n"])
    try:
        result = subprocess.run(
            ["bluetoothctl"],
            input=input_str,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout bluetoothctl")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def parse_devices_from_output(output: str) -> list[dict]:
    """Parse 'Device XX:XX:XX:XX:XX:XX Name' lines."""
    devices = []
    seen = set()
    for line in output.splitlines():
        m = re.search(r"Device\s+([0-9A-Fa-f:]{17})\s+(.*)", line)
        if m:
            addr = m.group(1).strip()
            name = m.group(2).strip()
            if addr not in seen:
                seen.add(addr)
                devices.append({"address": addr, "name": name or addr})
    return devices


def get_device_info(address: str) -> dict:
    """Get detailed info for a single device."""
    output = run_bluetoothctl(f"info {address}")
    info = {"address": address, "connected": False, "paired": False, "trusted": False, "name": address, "rssi": None}
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Name:"):
            info["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Connected:"):
            info["connected"] = line.split(":", 1)[1].strip() == "yes"
        elif line.startswith("Paired:"):
            info["paired"] = line.split(":", 1)[1].strip() == "yes"
        elif line.startswith("Trusted:"):
            info["trusted"] = line.split(":", 1)[1].strip() == "yes"
        elif line.startswith("RSSI:"):
            try:
                info["rssi"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return info


def get_pulse_sink(address: str) -> Optional[str]:
    """Find the PulseAudio sink name for a Bluetooth address."""
    clean = address.replace(":", "_")
    try:
        result = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if clean in line and "a2dp" in line:
                return line.split()[1]
        # Fallback: return any bluez sink containing the address
        for line in result.stdout.splitlines():
            if clean in line:
                return line.split()[1]
    except Exception:
        pass
    return None


def set_default_sink(address: str) -> bool:
    sink = get_pulse_sink(address)
    if sink:
        try:
            subprocess.run(["pactl", "set-default-sink", sink], timeout=5)
            log.info(f"Sink par défaut: {sink}")
            return True
        except Exception:
            pass
    return False


# ─── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(title="Bluetooth Speaker Manager", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectRequest(BaseModel):
    address: str
    set_default: bool = True


class RenameRequest(BaseModel):
    address: str
    name: str


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/scan")
async def scan_devices():
    """Scan for nearby Bluetooth devices."""
    log.info("Scan Bluetooth en cours...")
    output = run_bluetoothctl(
        "power on",
        f"scan on",
        timeout=SCAN_TIMEOUT + 5
    )
    # Also list already-known devices
    known_output = run_bluetoothctl("devices")
    all_output = output + known_output
    devices = parse_devices_from_output(all_output)
    
    # Enrich with detailed info
    enriched = []
    for d in devices:
        try:
            info = get_device_info(d["address"])
            enriched.append(info)
        except Exception:
            enriched.append(d)
    
    log.info(f"Scan terminé: {len(enriched)} appareils trouvés")
    return {"devices": enriched}


@app.get("/api/devices")
async def list_devices():
    """List paired/trusted devices."""
    output = run_bluetoothctl("devices Paired")
    devices = parse_devices_from_output(output)
    enriched = []
    for d in devices:
        try:
            info = get_device_info(d["address"])
            enriched.append(info)
        except Exception:
            enriched.append(d)
    return {"devices": enriched}


@app.post("/api/pair")
async def pair_device(req: ConnectRequest):
    """Pair, trust, and connect a Bluetooth device."""
    addr = req.address
    log.info(f"Pairing {addr}...")
    
    output = run_bluetoothctl(
        "power on",
        f"pair {addr}",
        timeout=30
    )
    if "Failed" in output and "already" not in output.lower():
        raise HTTPException(status_code=400, detail=f"Echec du pairing: {output}")
    
    run_bluetoothctl(f"trust {addr}")
    output2 = run_bluetoothctl(f"connect {addr}", timeout=20)
    
    if "Failed to connect" in output2:
        raise HTTPException(status_code=400, detail="Appareil pairé mais connexion échouée. Vérifiez qu'il est en mode appairage.")
    
    # Persist in trusted list
    devices = load_trusted_devices()
    if not any(d["address"] == addr for d in devices):
        info = get_device_info(addr)
        devices.append({"address": addr, "name": info.get("name", addr)})
        save_trusted_devices(devices)
    
    # Set as default PulseAudio sink
    default_set = False
    if req.set_default:
        await asyncio.sleep(2)  # Wait for PA to register the sink
        default_set = set_default_sink(addr)
    
    return {
        "success": True,
        "message": f"Enceinte {addr} connectée avec succès",
        "default_sink_set": default_set
    }


@app.post("/api/connect")
async def connect_device(req: ConnectRequest):
    """Connect an already-paired device."""
    addr = req.address
    log.info(f"Connexion de {addr}...")
    
    output = run_bluetoothctl(f"connect {addr}", timeout=20)
    if "Failed to connect" in output:
        raise HTTPException(status_code=400, detail="Connexion échouée. L'enceinte est-elle allumée et à portée ?")
    
    default_set = False
    if req.set_default:
        await asyncio.sleep(2)
        default_set = set_default_sink(addr)
    
    return {
        "success": True,
        "message": f"Connecté à {addr}",
        "default_sink_set": default_set
    }


@app.post("/api/disconnect")
async def disconnect_device(req: ConnectRequest):
    """Disconnect a device."""
    addr = req.address
    log.info(f"Déconnexion de {addr}...")
    run_bluetoothctl(f"disconnect {addr}")
    return {"success": True, "message": f"Déconnecté de {addr}"}


@app.delete("/api/remove/{address}")
async def remove_device(address: str):
    """Remove/unpair a device."""
    log.info(f"Suppression de {address}...")
    run_bluetoothctl(
        f"disconnect {address}",
        f"untrust {address}",
        f"remove {address}",
    )
    # Remove from persistent store
    devices = [d for d in load_trusted_devices() if d["address"] != address]
    save_trusted_devices(devices)
    return {"success": True, "message": f"Appareil {address} supprimé"}


@app.get("/api/sinks")
async def list_sinks():
    """List PulseAudio sinks."""
    try:
        result = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            capture_output=True, text=True, timeout=5
        )
        sinks = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                sinks.append({"id": parts[0], "name": parts[1], "state": parts[4] if len(parts) > 4 else "unknown"})
        return {"sinks": sinks}
    except Exception as e:
        return {"sinks": [], "error": str(e)}


@app.post("/api/set-default-sink/{address}")
async def api_set_default_sink(address: str):
    """Set a Bluetooth device as the default PulseAudio output."""
    ok = set_default_sink(address)
    if not ok:
        raise HTTPException(status_code=404, detail="Sink PulseAudio non trouvé pour cet appareil. L'enceinte est-elle connectée ?")
    return {"success": True}


@app.get("/api/status")
async def status():
    """General status: BT adapter + connected devices."""
    try:
        result = subprocess.run(["hciconfig"], capture_output=True, text=True, timeout=5)
        adapter_up = "UP RUNNING" in result.stdout
    except Exception:
        adapter_up = False
    
    try:
        result2 = subprocess.run(
            ["pactl", "info"],
            capture_output=True, text=True, timeout=5
        )
        pulse_ok = result2.returncode == 0
        default_sink = ""
        for line in result2.stdout.splitlines():
            if "Default Sink:" in line:
                default_sink = line.split(":", 1)[1].strip()
    except Exception:
        pulse_ok = False
        default_sink = ""
    
    return {
        "adapter_up": adapter_up,
        "pulseaudio_ok": pulse_ok,
        "default_sink": default_sink,
        "trusted_devices": load_trusted_devices()
    }


# ─── Embedded HTML UI ─────────────────────────────────────────────────────────

HTML_UI = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bluetooth Speaker Manager</title>
<style>
  :root {
    --ha-blue: #03a9f4;
    --ha-dark: #1c1c1e;
    --ha-card: #2c2c2e;
    --ha-border: #3a3a3c;
    --ha-text: #e5e5ea;
    --ha-sub: #8e8e93;
    --ha-green: #30d158;
    --ha-red: #ff453a;
    --ha-orange: #ff9f0a;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--ha-dark); color: var(--ha-text); font-family: -apple-system, sans-serif; min-height: 100vh; }
  header { background: var(--ha-card); border-bottom: 1px solid var(--ha-border); padding: 16px 20px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 1.2rem; font-weight: 600; }
  .badge { background: var(--ha-blue); color: #fff; border-radius: 12px; font-size: 0.7rem; padding: 2px 8px; }
  main { max-width: 720px; margin: 0 auto; padding: 20px; display: flex; flex-direction: column; gap: 20px; }
  .card { background: var(--ha-card); border-radius: 14px; border: 1px solid var(--ha-border); overflow: hidden; }
  .card-header { padding: 14px 18px; border-bottom: 1px solid var(--ha-border); display: flex; align-items: center; justify-content: space-between; }
  .card-header h2 { font-size: 1rem; font-weight: 600; }
  .card-body { padding: 16px 18px; }
  button { cursor: pointer; border: none; border-radius: 10px; font-size: 0.9rem; font-weight: 500; padding: 8px 16px; transition: opacity .15s; }
  button:hover { opacity: .8; }
  button:disabled { opacity: .4; cursor: not-allowed; }
  .btn-primary { background: var(--ha-blue); color: #fff; }
  .btn-success { background: var(--ha-green); color: #fff; }
  .btn-danger { background: var(--ha-red); color: #fff; }
  .btn-neutral { background: var(--ha-border); color: var(--ha-text); }
  .btn-sm { padding: 5px 10px; font-size: 0.8rem; }
  .status-row { display: flex; gap: 12px; flex-wrap: wrap; }
  .stat { background: var(--ha-dark); border-radius: 10px; padding: 10px 14px; flex: 1; min-width: 120px; }
  .stat label { font-size: 0.7rem; color: var(--ha-sub); display: block; margin-bottom: 4px; text-transform: uppercase; letter-spacing: .05em; }
  .stat span { font-size: 1rem; font-weight: 600; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .dot.green { background: var(--ha-green); }
  .dot.red { background: var(--ha-red); }
  .dot.orange { background: var(--ha-orange); }
  .device-list { display: flex; flex-direction: column; gap: 8px; }
  .device-item { background: var(--ha-dark); border-radius: 10px; padding: 12px 14px; display: flex; align-items: center; gap: 12px; }
  .device-icon { font-size: 1.4rem; flex-shrink: 0; }
  .device-info { flex: 1; min-width: 0; }
  .device-name { font-weight: 600; font-size: 0.95rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .device-addr { font-size: 0.75rem; color: var(--ha-sub); margin-top: 2px; }
  .device-actions { display: flex; gap: 6px; flex-shrink: 0; flex-wrap: wrap; justify-content: flex-end; }
  .empty { text-align: center; color: var(--ha-sub); padding: 24px 0; font-size: 0.9rem; }
  .log-box { background: #000; border-radius: 10px; padding: 12px; font-family: monospace; font-size: 0.78rem; max-height: 180px; overflow-y: auto; color: #0f0; }
  .log-entry { margin-bottom: 2px; }
  .log-entry.err { color: var(--ha-red); }
  .log-entry.warn { color: var(--ha-orange); }
  .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid transparent; border-top-color: currentColor; border-radius: 50%; animation: spin .6s linear infinite; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .toast { position: fixed; bottom: 20px; right: 20px; background: var(--ha-card); border: 1px solid var(--ha-border); border-radius: 12px; padding: 12px 18px; font-size: 0.9rem; box-shadow: 0 4px 24px #0008; opacity: 0; transform: translateY(10px); transition: all .3s; pointer-events: none; max-width: 300px; z-index: 100; }
  .toast.show { opacity: 1; transform: none; }
  .toast.success { border-left: 4px solid var(--ha-green); }
  .toast.error { border-left: 4px solid var(--ha-red); }
</style>
</head>
<body>
<header>
  <span style="font-size:1.6rem">🔊</span>
  <h1>Bluetooth Speaker Manager</h1>
  <span class="badge" id="version">v1.0</span>
</header>
<main>

  <!-- Status Card -->
  <div class="card">
    <div class="card-header">
      <h2>État du système</h2>
      <button class="btn-neutral btn-sm" onclick="refreshStatus()">↻ Actualiser</button>
    </div>
    <div class="card-body">
      <div class="status-row" id="statusRow">
        <div class="stat"><label>Adaptateur BT</label><span id="adapterStatus">—</span></div>
        <div class="stat"><label>PulseAudio</label><span id="pulseStatus">—</span></div>
        <div class="stat"><label>Sortie par défaut</label><span id="defaultSink" style="font-size:.8rem;word-break:break-all">—</span></div>
      </div>
    </div>
  </div>

  <!-- Scan Card -->
  <div class="card">
    <div class="card-header">
      <h2>Scan Bluetooth</h2>
      <button class="btn-primary" id="scanBtn" onclick="startScan()">🔍 Scanner</button>
    </div>
    <div class="card-body">
      <div id="scanResults">
        <div class="empty">Lance un scan pour détecter les enceintes à portée</div>
      </div>
    </div>
  </div>

  <!-- Paired Devices Card -->
  <div class="card">
    <div class="card-header">
      <h2>Appareils enregistrés</h2>
      <button class="btn-neutral btn-sm" onclick="loadPaired()">↻</button>
    </div>
    <div class="card-body">
      <div id="pairedList" class="device-list">
        <div class="empty">Aucun appareil enregistré</div>
      </div>
    </div>
  </div>

  <!-- Log Card -->
  <div class="card">
    <div class="card-header">
      <h2>Journal</h2>
      <button class="btn-neutral btn-sm" onclick="clearLog()">Vider</button>
    </div>
    <div class="card-body">
      <div class="log-box" id="logBox"></div>
    </div>
  </div>

</main>
<div class="toast" id="toast"></div>

<script>
const BASE = '';

function log(msg, type='') {
  const box = document.getElementById('logBox');
  const d = document.createElement('div');
  d.className = 'log-entry ' + type;
  d.textContent = new Date().toLocaleTimeString() + ' › ' + msg;
  box.prepend(d);
  while (box.children.length > 80) box.removeChild(box.lastChild);
}
function clearLog() { document.getElementById('logBox').innerHTML = ''; }

function toast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + type;
  setTimeout(() => t.classList.remove('show'), 3500);
}

async function apiFetch(url, opts={}) {
  try {
    const r = await fetch(BASE + url, { headers: {'Content-Type': 'application/json'}, ...opts });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Erreur serveur');
    return data;
  } catch (e) {
    log(e.message, 'err');
    toast(e.message, 'error');
    throw e;
  }
}

async function refreshStatus() {
  const s = await apiFetch('/api/status');
  document.getElementById('adapterStatus').innerHTML =
    `<span class="dot ${s.adapter_up ? 'green' : 'red'}"></span>${s.adapter_up ? 'Actif' : 'Hors ligne'}`;
  document.getElementById('pulseStatus').innerHTML =
    `<span class="dot ${s.pulseaudio_ok ? 'green' : 'red'}"></span>${s.pulseaudio_ok ? 'OK' : 'Arrêté'}`;
  document.getElementById('defaultSink').textContent = s.default_sink || '(aucune)';
}

async function startScan() {
  const btn = document.getElementById('scanBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Scan...';
  document.getElementById('scanResults').innerHTML = '<div class="empty"><span class="spinner"></span> Recherche en cours...</div>';
  log('Démarrage du scan Bluetooth...');
  try {
    const data = await apiFetch('/api/scan');
    renderScanResults(data.devices);
    log(`Scan terminé: ${data.devices.length} appareils trouvés`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🔍 Scanner';
  }
}

function renderScanResults(devices) {
  const el = document.getElementById('scanResults');
  if (!devices.length) {
    el.innerHTML = '<div class="empty">Aucun appareil détecté. L\'enceinte est-elle en mode appairage ?</div>';
    return;
  }
  el.innerHTML = '';
  const list = document.createElement('div');
  list.className = 'device-list';
  devices.forEach(d => {
    list.appendChild(deviceCard(d, 'scan'));
  });
  el.appendChild(list);
}

async function loadPaired() {
  const data = await apiFetch('/api/devices');
  const el = document.getElementById('pairedList');
  if (!data.devices.length) {
    el.innerHTML = '<div class="empty">Aucun appareil enregistré</div>';
    return;
  }
  el.innerHTML = '';
  data.devices.forEach(d => el.appendChild(deviceCard(d, 'paired')));
}

function deviceCard(d, mode) {
  const div = document.createElement('div');
  div.className = 'device-item';
  const isConnected = d.connected;
  div.innerHTML = `
    <div class="device-icon">${isConnected ? '🔊' : '🔇'}</div>
    <div class="device-info">
      <div class="device-name">${escHtml(d.name || d.address)}</div>
      <div class="device-addr">
        <span class="dot ${isConnected ? 'green' : d.paired ? 'orange' : 'red'}"></span>
        ${d.address} ${isConnected ? '· Connecté' : d.paired ? '· Pairé' : '· Non pairé'}
        ${d.rssi ? ' · ' + d.rssi + ' dBm' : ''}
      </div>
    </div>
    <div class="device-actions" id="actions-${d.address.replace(/:/g,'_')}"></div>
  `;
  const actions = div.querySelector('.device-actions');

  if (mode === 'scan') {
    if (!d.connected) {
      const btnPair = document.createElement('button');
      btnPair.className = 'btn-primary btn-sm';
      btnPair.textContent = d.paired ? '↺ Connecter' : '+ Appairer';
      btnPair.onclick = () => d.paired ? connectDevice(d.address, btnPair) : pairDevice(d.address, btnPair);
      actions.appendChild(btnPair);
    } else {
      const btnDisc = document.createElement('button');
      btnDisc.className = 'btn-neutral btn-sm';
      btnDisc.textContent = 'Déconnecter';
      btnDisc.onclick = () => disconnectDevice(d.address, btnDisc);
      actions.appendChild(btnDisc);

      const btnDefault = document.createElement('button');
      btnDefault.className = 'btn-success btn-sm';
      btnDefault.textContent = '🎵 Défaut';
      btnDefault.onclick = () => setDefault(d.address, btnDefault);
      actions.appendChild(btnDefault);
    }
  } else {
    if (d.connected) {
      const btnDisc = document.createElement('button');
      btnDisc.className = 'btn-neutral btn-sm';
      btnDisc.textContent = 'Déconnecter';
      btnDisc.onclick = () => disconnectDevice(d.address, btnDisc);
      actions.appendChild(btnDisc);

      const btnDefault = document.createElement('button');
      btnDefault.className = 'btn-success btn-sm';
      btnDefault.textContent = '🎵 Défaut';
      btnDefault.onclick = () => setDefault(d.address, btnDefault);
      actions.appendChild(btnDefault);
    } else {
      const btnConn = document.createElement('button');
      btnConn.className = 'btn-primary btn-sm';
      btnConn.textContent = 'Connecter';
      btnConn.onclick = () => connectDevice(d.address, btnConn);
      actions.appendChild(btnConn);
    }
    const btnDel = document.createElement('button');
    btnDel.className = 'btn-danger btn-sm';
    btnDel.textContent = '🗑';
    btnDel.title = 'Supprimer';
    btnDel.onclick = () => removeDevice(d.address, btnDel);
    actions.appendChild(btnDel);
  }
  return div;
}

async function pairDevice(addr, btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  log(`Appairage de ${addr}...`);
  try {
    const r = await apiFetch('/api/pair', {method:'POST', body: JSON.stringify({address: addr, set_default: true})});
    toast(r.message, 'success');
    log(r.message);
    loadPaired();
    refreshStatus();
  } finally {
    btn.disabled = false;
    btn.textContent = '+ Appairer';
  }
}

async function connectDevice(addr, btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  log(`Connexion à ${addr}...`);
  try {
    const r = await apiFetch('/api/connect', {method:'POST', body: JSON.stringify({address: addr, set_default: true})});
    toast(r.message, 'success');
    log(r.message);
    loadPaired();
    refreshStatus();
  } finally {
    btn.disabled = false;
    btn.textContent = 'Connecter';
  }
}

async function disconnectDevice(addr, btn) {
  btn.disabled = true;
  log(`Déconnexion de ${addr}...`);
  try {
    const r = await apiFetch('/api/disconnect', {method:'POST', body: JSON.stringify({address: addr})});
    toast(r.message, 'success');
    log(r.message);
    loadPaired();
    refreshStatus();
  } finally {
    btn.disabled = false;
    btn.textContent = 'Déconnecter';
  }
}

async function removeDevice(addr, btn) {
  if (!confirm(`Supprimer et désappairer ${addr} ?`)) return;
  btn.disabled = true;
  log(`Suppression de ${addr}...`);
  try {
    const r = await apiFetch(`/api/remove/${addr}`, {method:'DELETE'});
    toast(r.message, 'success');
    log(r.message);
    loadPaired();
  } finally {
    btn.disabled = false;
  }
}

async function setDefault(addr, btn) {
  btn.disabled = true;
  log(`Définir ${addr} comme sortie par défaut...`);
  try {
    await apiFetch(`/api/set-default-sink/${addr}`, {method:'POST'});
    toast('Sortie audio par défaut mise à jour', 'success');
    log('Sortie par défaut: ' + addr);
    refreshStatus();
  } finally {
    btn.disabled = false;
  }
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Init
refreshStatus();
loadPaired();
setInterval(refreshStatus, 30000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def ui():
    return HTMLResponse(content=HTML_UI)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7880, log_level=LOG_LEVEL)
