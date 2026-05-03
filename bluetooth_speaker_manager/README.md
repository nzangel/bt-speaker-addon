# Bluetooth Speaker Manager — Add-on Home Assistant

Connectez et gérez n'importe quelle enceinte Bluetooth (A2DP) depuis une interface web intégrée dans Home Assistant.

## Fonctionnalités

- 🔍 **Scan** des appareils Bluetooth à portée
- 🔗 **Appairage** en un clic (pair + trust + connect)
- 🎵 **Définir l'enceinte comme sortie audio par défaut** (PulseAudio)
- 🔄 **Reconnexion automatique** après redémarrage
- 🗑️ **Suppression** / désappairage
- 📋 Journal des événements intégré

## Installation

### 1. Ajouter le dépôt

Dans Home Assistant :
1. **Paramètres → Add-ons → Store des add-ons**
2. Cliquez sur les **⋮ (trois points)** en haut à droite
3. Choisissez **"Dépôts"**
4. Ajoutez l'URL de ce dépôt GitHub

### 2. Installer l'add-on

1. Cherchez **"Bluetooth Speaker Manager"** dans le store
2. Cliquez **Installer**
3. Activez **"Afficher dans la barre latérale"**
4. Cliquez **Démarrer**

### 3. Prérequis matériels

- Un adaptateur Bluetooth USB (ou intégré) reconnu par Linux/BlueZ
- **Home Assistant OS** (recommandé) — le Bluetooth est géré automatiquement
- Pour HAOS sur VM : passez l'adaptateur BT en USB passthrough

## Utilisation

### Connecter une enceinte

1. **Mettez votre enceinte en mode appairage** (bouton Bluetooth maintenu)
2. Ouvrez **BT Speaker** dans la barre latérale HA
3. Cliquez **🔍 Scanner**
4. Cliquez **+ Appairer** sur votre enceinte
5. L'enceinte devient automatiquement la sortie audio par défaut

### Utiliser dans les automatisations (TTS)

Une fois l'enceinte connectée et définie comme sortie par défaut, utilisez le service `tts.speak` normalement :

```yaml
service: tts.google_translate_say
data:
  entity_id: media_player.vlc_telnet
  message: "Bonjour depuis Home Assistant"
```

Pour les annonces audio, combinez avec l'add-on **VLC Telnet** ou **Music Player Daemon**.

### API REST

L'add-on expose une API sur le port 7880 :

| Endpoint | Méthode | Description |
|---|---|---|
| `/api/scan` | GET | Scanner les appareils BT |
| `/api/devices` | GET | Lister les appareils pairés |
| `/api/pair` | POST | Appairer et connecter `{"address":"XX:XX..."}` |
| `/api/connect` | POST | Connecter un appareil pairé |
| `/api/disconnect` | POST | Déconnecter |
| `/api/remove/{address}` | DELETE | Supprimer / désappairer |
| `/api/set-default-sink/{address}` | POST | Définir comme sortie PulseAudio |
| `/api/status` | GET | État général (adaptateur, PulseAudio...) |

## Limitations connues

- **A2DP uniquement** : profil audio haute qualité pour écoute. HFP (mains-libres) non supporté.
- **Pas de multiroom** : chaque enceinte est une sortie PulseAudio indépendante.
- Les enceintes à **adresse MAC aléatoire** (certains modèles récents) ne peuvent pas être reconnectées automatiquement.

## Dépannage

### L'enceinte ne se connecte pas
- Vérifiez qu'elle est bien en **mode appairage** (clignotant)
- Essayez de la **déappairer** sur le téléphone si elle y était connectée
- Relancez un **scan** après avoir rapproché l'enceinte

### Pas de son après connexion
- Cliquez **🎵 Défaut** pour définir l'enceinte comme sortie PulseAudio
- Vérifiez dans `Paramètres → Audio` de HA que la sortie est bien sélectionnée
- Redémarrez l'add-on

### PulseAudio indiqué "Arrêté"
- Redémarrez l'add-on depuis `Paramètres → Add-ons`
- Vérifiez les logs de l'add-on pour plus de détails

## Architecture technique

```
bluetoothctl (BlueZ)
    └── Appairage / connexion BT
PulseAudio
    ├── module-bluetooth-discover
    └── module-bluetooth-policy
FastAPI (Python)
    └── Interface web + API REST → port 7880
```
