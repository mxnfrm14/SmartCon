# Firmware ESP32 SmartCon

Ce dossier contient l’application ESP-IDF embarquée sur l’ESP32. Elle relie les
profils Bluetooth classiques de l’iPhone au transport USB série utilisé par
l’application Windows SmartCon.

Pour la vue d’ensemble et les étapes d’utilisation, commencer par le
[README du projet](../README.md). Les instructions côté PC sont dans
[pc/README.md](../pc/README.md).

## Fonctions du firmware

- Client **HFP** pour les appels et la liaison audio vocale.
- Réception des médias **A2DP** et transfert des paquets SBC compressés au PC.
- Transport série bidirectionnel à **921 600 bauds**, pour l’audio, les états et
  les commandes de gestion.
- Appairage avec comparaison numérique et approbation explicite depuis
  l’application Windows.
- Liste de téléphones autorisés conservée en NVS ; un seul téléphone est actif à
  la fois.

Le firmware ne produit pas directement le son sur une sortie analogique :
l’audio HFP transite par le contrôleur Bluetooth en HCI, puis par USB vers le PC.
Les médias restent compressés en SBC sur le transport série ; le PC les décode.
Le microphone USB série du PC n’est accepté que pendant une liaison vocale active.

## Prérequis

- ESP-IDF **6.1** avec les outils de compilation installés et le terminal ESP-IDF initialisé.
- Une carte ESP32 avec Bluetooth classique et un port série USB. La cible validée
  dans ce projet est `esp32`.
- Un téléphone iPhone et l’application Windows SmartCon pour approuver et gérer
  les téléphones.

L’adaptateur de sécurité de l’appairage utilise des points internes de Bluedroid
et est lié à ESP-IDF 6.1. Toute mise à niveau majeure d’ESP-IDF doit inclure une
revue de `pairing_security.c` et de ses signatures.

## Compiler et flasher

Fermer SmartCon, `listen.py`, `idf.py monitor` et tout autre programme qui tient
le port série. Dans un terminal initialisé avec ESP-IDF, depuis la racine du
dépôt :

```powershell
idf.py -B build_audio_pc -p COM3 build flash
```

Remplacer `COM3` par le port attribué à la carte. Pour seulement compiler :

```powershell
idf.py -B build_audio_pc build
```

Le moniteur série peut être lancé après la fermeture de l’application PC :

```powershell
idf.py -B build_audio_pc -p COM3 monitor
```

Le port série sert au transport binaire pendant l’utilisation. Le moniteur ne
doit donc pas fonctionner simultanément avec l’application Windows.

## Appairage et autorisations

Le firmware n’autorise pas automatiquement les appareils Bluetooth qui se
présentent. L’application Windows ouvre une fenêtre d’appairage temporaire,
affiche le code de comparaison et envoie l’approbation explicite. Les appareils
approuvés sont mémorisés dans la NVS de la carte ; le changement de PC ne les
efface pas. Un seul téléphone peut utiliser les profils audio à la fois.

Mettre à jour le firmware et l’application Windows ensemble : les commandes de
gestion de téléphones ne sont pas prises en charge par les anciennes versions.
En cas de nouvel appairage après une mise à jour, supprimer aussi l’ancien lien
SmartCon des réglages Bluetooth de l’iPhone si nécessaire.

## Organisation des sources

| Fichier | Rôle |
| --- | --- |
| `main.c` | Initialisation des composants, Bluetooth et transport série |
| `bt_app_hf.c` | Client HFP et états d’appel |
| `bt_app_media.c` | Réception et transfert des médias A2DP/SBC |
| `audio_serial.c` | Trames binaires audio sur USB série |
| `phone_manager.c` | Téléphones autorisés, sélection et connexions Bluetooth |
| `pairing_security.c` | Comparaison numérique et validation de l’approbation |
| `bt_app_pbac.c` | Prise en charge du profil d’accès au répertoire téléphonique |

Le protocole de commandes est défini et documenté dans le dossier de projet
[`ETAT_DU_PROJET.md`](../ETAT_DU_PROJET.md). Le firmware ne stocke ni n’enregistre
les conversations.
