# SmartCon — dossier de projet

**État au 18 octobre 2026 · Version documentaire 1.1**  
**Répertoire de travail :** `C:\esp\phone_bridge`  
**Objet :** utiliser le casque et le microphone du PC Windows pour les appels de l’iPhone, et écouter sur le PC sa musique et le son de ses vidéos.

Ce document distingue les fonctions implémentées, les essais réellement effectués et les validations encore nécessaires. Les captures du 17 octobre restent des preuves historiques ; les procédures et le bilan ci-dessous décrivent la version courante.

## 1. Situation actuelle

Le projet s’appelle **SmartCon**, aussi bien dans la liste Bluetooth de l’iPhone que dans l’application Windows. L’ESP32 reçoit les appels HFP et les médias A2DP ; le PC restitue le son et fournit le microphone par USB-série. L’application autonome est disponible dans **`dist\SmartCon\SmartCon.exe`** et embarque Python et ses dépendances.

Le firmware courant a été **compilé puis flashé sur COM3 le 18 octobre**, avec vérification des données écrites et conservation de l’appairage. Il n’est pas nécessaire de refaire ce flash pour utiliser l’exécutable courant.

Après l’ajout de la gestion des téléphones, deux régressions ont été corrigées : l’échec d’appairage avant affichage du numéro, puis les connexions instables et les médias absents ou disponibles seulement après un appel. Les connexions des profils sont maintenant séquencées, les tentatives en cours suivies, et la sélection du téléphone déjà actif conserve ses liens. Les callbacks audio ne prennent plus le verrou des commandes et des écritures NVS : ils lisent des autorisations atomiques. La fermeture du lien vocal libère explicitement l’état micro.

L’essai direct après le dernier flash a confirmé **HFP et A2DP connectés**, puis une lecture média sans appel préalable : **plus de 2 000 paquets**, **aucune perte série**, **aucune erreur SBC** et **aucun paquet rejeté par l’autorisation**. L’utilisateur a confirmé « Music/video plays normally », puis **« ok it seems to work fine now »**. Le diagnostic utilisait l’écoute seule et a libéré COM3 après l’essai.

Ce résultat valide le rétablissement de l’appairage, de la connexion et des médias sur cette installation. Il ne constitue pas une mesure de stabilité de plusieurs heures. Les appels descendants ont été signalés comme fonctionnels par l’utilisateur ; **le microphone reste à vérifier pendant un appel réel**.

| Fonction | État au 18 octobre 2026 |
| --- | --- |
| Nom Bluetooth et application | **SmartCon** |
| Compilation et flash ESP32 sur COM3 | Réussis ; appairage conservé ; 19 % de marge dans la partition application |
| Appairage contrôlé | Confirmé sur l’iPhone après correction ; comparaison du numéro et approbation depuis l’application |
| Appairage verrouillé par défaut | Implémenté ; ouverture explicite de 60 s, annulation, refus et expiration côté ESP32 |
| Téléphones autorisés | Jusqu’à six mémorisés en NVS ; un seul sélectionné pour les appels et les médias |
| Sélection, déconnexion et oubli | Implémentés dans l’application ; changement entre deux téléphones distincts encore à tester |
| Médias A2DP/SBC | Lecture normale confirmée sur le matériel ; aucune perte ni erreur pendant l’essai court |
| Appels iPhone vers casque PC | Fonctionnement signalé par l’utilisateur ; qualité et conversation prolongée à consigner |
| Microphone PC vers iPhone | Implémenté ; validation d’intelligibilité toujours à faire |
| Musique → appel → musique | Logique de priorité et libération de l’état vocal corrigées ; cycle complet avec micro à formaliser |
| Application Windows | Icône près de l’horloge, démarrer/arrêter, choix COM/casque/micro, état et fermeture complète |
| Réglages et démarrage Windows | Implémentés ; option de démarrage automatique et chemin de l’exécutable mémorisés ; nouvelle session Windows à vérifier |
| Exécutable autonome | `dist\SmartCon\SmartCon.exe` généré ; lancement, création du décodeur SBC et arrêt vérifiés |
| Tests automatiques | **23 tests réussis** ; un groupe de tests C natifs ignoré faute de compilateur hôte x86-64 |
| Commandes média et volume absolu AVRCP | Non implémentés dans l’application |
| Latence vidéo, dérive et stabilité longue durée | À mesurer |

## 2. Besoin et périmètre

Le besoin initial est de conserver le casque USB et son microphone sur le PC tout en les utilisant pour les appels de l’iPhone. L’extension ajoutée permet de recevoir aussi les médias de l’iPhone sur ce même casque, sans changer de branchement.

L’ESP32 joue le rôle d’accessoire Bluetooth audio auprès de l’iPhone. Le PC assure la restitution sonore, la capture du microphone et le décodage des médias. L’iPhone reste chargé des appels, des applications de lecture et du choix de sortie audio.

Le lecteur envoie directement le son au périphérique Windows sélectionné. Le projet ne crée actuellement **aucun périphérique audio virtuel Windows** : le son reçu n’est donc pas automatiquement une entrée sélectionnable dans OBS, Discord ou une autre application. Une telle intégration constituerait une évolution distincte.

La cible utilisée et validée pour la compilation est `esp32`. Des fichiers hérités mentionnent également ESP32-S31 ; leur présence ne prouve pas que cette installation a été testée sur cette autre cible.

## 3. Matériel utilisé

| Élément | Informations observées | Rôle |
| --- | --- | --- |
| iPhone | Modèle et version iOS non relevés | Source des appels et des médias Bluetooth |
| Carte ESP32 | Puce **ESP32-D0WD-V3**, révision **v3.1** ; référence commerciale de la carte non relevée | Pont Bluetooth vers liaison série |
| Fréquence processeur | **160 MHz** au démarrage observé | Exécution du firmware et des tâches Bluetooth |
| Mémoire flash | **4 Mo détectés** ; image configurée pour **2 Mo** | Stockage du firmware et des données persistantes |
| Interface USB-série | **Silicon Labs CP210x USB to UART Bridge**, VID:PID `10C4:EA60` | Connexion série de la carte au PC |
| Port Windows | **COM3** sur l’installation actuelle | Transport audio et programmation |
| Câble USB | Câble de données ; référence/connecteur exacts non relevés | Liaison carte–PC et alimentation dans le montage courant |
| PC | Windows ; version précise et configuration CPU/RAM non relevées | Exécution du lecteur et gestion des périphériques audio |
| Casque et microphone | Périphériques exposés comme **HyperX Virtual Surround Sound** ; modèle commercial exact non relevé | Écoute et capture de la voix |

Sous Windows WASAPI, les indices détectés sont **13 pour la sortie HyperX** et **15 pour son microphone**. Ces indices dépendent de la machine et peuvent changer après une modification des périphériques ou des pilotes.

Un microphone **Aukey-PC-LM1E Audio** apparaît aussi dans la liste Windows. Il n’est pas la source sélectionnée dans la commande de référence du projet. COM1 est également présent, mais n’est pas le port utilisé pour l’ESP32.

Aucun DAC, amplificateur, microphone analogique ou câblage I2S/PCM externe n’est utilisé dans le trajet audio actuel. Les fichiers de configuration GPIO PCM proviennent de l’exemple d’origine ; la configuration active transporte la voix par **HCI**.

### Informations matérielles à compléter

Pour rendre l’installation entièrement reproductible, relever le modèle d’iPhone, la version iOS, la référence exacte de la carte ESP32, le modèle du casque, la version de Windows et le pilote CP210x utilisé. Une photo du montage pourra compléter ce dossier ultérieurement.

## 4. Architecture générale

```text
                           Bluetooth Classic
                    +---------------------------+
                    |                           |
                 iPhone                       ESP32
                    |                           |
                    |  HFP : voix des appels     |
                    +-------------------------->|
                    |<--------------------------+
                    |  HFP : voix du micro PC    |
                    |                           |
                    +-------------------------->|
                       A2DP : médias SBC stéréo  |
                                                |
                                   USB-série / UART0
                                     921600 bauds
                                                |
                                          PC Windows
                                          pc/listen.py
                                         /           \
                               sortie audio        entrée audio
                               casque HyperX       micro HyperX
```

### Appel : iPhone vers casque

L’iPhone transmet la voix en HFP. Le firmware récupère les échantillons décodés par la pile Bluetooth, les place dans des paquets série puis les envoie au PC. Le lecteur les adapte à 48 kHz et duplique le signal mono sur les deux canaux du casque.

### Appel : microphone vers iPhone

Le PC capture le microphone à 48 kHz, ramène le signal en mono à 8 ou 16 kHz selon l’appel puis l’envoie à la carte. Le firmware remplit le flux audio HFP montant avec ces données. Si elles manquent, il fournit du silence.

### Musique et vidéos

L’iPhone transmet les médias en A2DP avec le codec SBC. L’ESP32 conserve ce flux **compressé** et l’envoie au PC. PyAV le décode, puis adapte la sortie à 48 kHz stéréo. Ce choix évite de faire passer du PCM stéréo à haut débit dans le port série.

## 5. Logiciels et environnement

| Composant | Version ou choix observé |
| --- | --- |
| ESP-IDF | **6.1.0**, installé dans `C:\esp\v6.1\esp-idf` |
| Cible et nom de projet | `esp32` ; projet CMake `SmartCon` |
| Firmware | C, FreeRTOS, pile Bluetooth Bluedroid |
| Construction | `idf.py`, CMake et Ninja |
| Python du lecteur | **3.14.3** dans `.venv-audio` |
| pyserial | **3.5** |
| sounddevice | **0.5.6** |
| PyAV | **17.1.0** |
| API audio sélectionnée dans les exemples | Windows WASAPI |
| Application Windows | Tkinter, pystray 0.19.5 et Pillow 12.3.0 |
| Paquet autonome | PyInstaller 6.22.3 ; Python et bibliothèques audio embarqués |

Les contraintes déclarées dans `pc/requirements.txt` sont `pyserial>=3.5,<4`, `sounddevice>=0.5,<1` et `av>=16,<18`. Les versions installées sont un relevé de cet environnement, pas un verrouillage exact des dépendances.

Le lecteur utilise les bibliothèques FFmpeg fournies avec la distribution binaire de PyAV ; aucun programme `ffmpeg.exe` séparé n’est lancé par le code.

## 6. Travail réalisé et décisions techniques

### 6.1 Adaptation de l’exemple Espressif

Le projet dérive d’un exemple **Hands-Free Client**. L’exemple contenait une console de commandes et des possibilités de routage audio PCM. Il a été adapté à un pont avec Windows : le port série transporte maintenant de l’audio binaire dans les deux sens et n’est plus une console interactive utilisable pendant l’écoute.

Le nom Bluetooth et le nom de projet sont maintenant `SmartCon`. Les captures historiques conservent les noms observés avant ce renommage. Le README racine contient encore une grande partie de l’exemple d’origine ; pour le fonctionnement actuel, utiliser ce dossier et [le guide PC](pc/README.md).

### 6.2 Réception des appels sur le PC

Le trajet audio HFP est configuré en **HCI**, pour rendre les données audio accessibles au logiciel. Le firmware transmet du PCM signé 16 bits mono. Le mode négocié détermine la fréquence : **8 kHz pour CVSD**, **16 kHz pour mSBC**. La préférence large bande est activée ; le mode réellement obtenu dépend de la négociation avec le téléphone.

### 6.3 Ajout du microphone Windows

La liaison série est devenue bidirectionnelle. Une tâche ESP32 reçoit les paquets micro, vérifie leur contenu et les conserve dans un tampon borné. Le lecteur accepte une entrée Windows mono ou stéréo et applique un gain réglable.

La capture du périphérique peut rester ouverte lorsque le lecteur fonctionne, mais **l’envoi du microphone est conditionné à la réception récente de voix d’appel**. Pendant un flux média, le lecteur n’envoie pas de données micro. Le firmware rejette aussi les paquets dont la fréquence ne correspond pas à l’appel actif.

### 6.4 Protection du transport et limitation du retard

Les paquets possèdent une signature, une longueur, un compteur et une somme de contrôle. Les récepteurs peuvent retrouver les trames après du texte de journalisation ou une corruption.

Les tâches Bluetooth n’attendent pas la disponibilité du port série : une file d’émission reçoit les données sans blocage. Si elle est pleine, des paquets peuvent être perdus ; cette décision évite de bloquer le traitement Bluetooth. Les compteurs de séquence permettent de repérer les trous.

### 6.5 Ajout A2DP stéréo

Une première option aurait consisté à réduire les médias en PCM mono pour tenir dans le débit série. Elle n’a pas été retenue. L’API de codec externe d’ESP-IDF permet de récupérer le SBC compressé : le transport actuel conserve donc la stéréo à **44,1 ou 48 kHz**, avec décodage sur le PC.

Le codec annoncé autorise les modes stéréo et stéréo jointe, 16 blocs, 8 sous-bandes, allocation loudness et un bitpool compris entre 2 et 53. AAC n’est pas activé dans la configuration actuelle.

### 6.6 Correction du démarrage A2DP

Après l’ajout A2DP, la carte pouvait disparaître de la liste Bluetooth. L’iPhone avait oublié l’accessoire, mais la cause du défaut de visibilité se situait dans le firmware :

```text
ESP_ERR_INVALID_STATE
esp_a2d_sink_register_stream_endpoint(0, &codec)
abort() ... Rebooting...
```

L’initialisation A2DP est asynchrone. Le code tentait d’enregistrer le codec immédiatement après la demande d’initialisation, avant que la pile soit prête. L’erreur déclenchait un arrêt puis un redémarrage en boucle, avant la mise en mode découvrable.

Le correctif attend maintenant **`ESP_A2D_PROF_STATE_EVT` avec `ESP_A2D_INIT_SUCCESS`** pour enregistrer le codec. Le résultat d’enregistrement est journalisé. Après compilation et flash, les journaux ont confirmé :

```text
Discoverable/connectable request: ESP_OK
Waiting for iPhone pairing as ESP_HFP_HF (no outgoing discovery)
HF PROF STATE: Init Complete
A2DP SBC endpoint ready
```

La leçon de cette étape est qu’une compilation réussie ne valide pas l’ordre des événements d’un système asynchrone. Le contrôle des journaux après flash reste indispensable.

### 6.7 Application Windows et gestion des téléphones

L’application `pc/tray_app.py` ajoute une icône dans la zone de notification Windows. Son menu permet de démarrer ou arrêter le pont, d’ouvrir les réglages et de quitter complètement. La fenêtre permet de choisir le port COM, la sortie audio et le microphone, et de gérer les téléphones enregistrés. Fermer la fenêtre la masque ; Quitter libère les ressources et le port série.

Les réglages et journaux se trouvent dans `%APPDATA%\SmartCon\settings.json` et `%APPDATA%\SmartCon\app.log`. Le journal est borné par rotation ; aucun audio n’est enregistré. Le démarrage Windows est une option pour l’utilisateur courant, enregistrée dans `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. Lorsque l’option est active, son chemin est actualisé vers l’exécutable courant lors de la sauvegarde.

Le firmware est l’autorité pour la liste des téléphones, les clés Bluetooth et le choix actif. La fenêtre d’appairage et ses 60 secondes restent appliquées même si l’application PC se ferme. La politique et l’adaptation de sécurité sont détaillées à la section 16.

### 6.8 Corrections de l’appairage et de la stabilité du 18 octobre

ESP-IDF pouvait accepter Just Works sans remonter de demande de confirmation à l’application. L’adaptateur `main/pairing_security.c` impose la comparaison numérique et refuse les confirmations automatiques dépourvues d’approbation USB valide. Il utilise deux interceptions de liaison limitées à **ESP-IDF 6.1** ; signatures et constantes sont vérifiées contre les en-têtes réels du SDK. Les profils d’un unique candidat peuvent se préparer pendant l’appairage, mais son audio reste bloqué jusqu’à l’approbation et l’authentification réussies.

Le gestionnaire attend ensuite que HFP et le point SBC soient initialisés, laisse une courte période de reconnexion au téléphone, puis établit les profils en séquence. Il suit les tentatives en cours et temporise les échecs. Une nouvelle activation du téléphone déjà sélectionné ne provoque plus de déconnexion.

Les autorisations des callbacks audio sont publiées par valeurs atomiques pour supprimer toute attente sur le verrou de gestion. L’événement de démarrage média remet à jour le lien et son identifiant autorisés ; la fin du lien vocal efface l’état micro susceptible de retenir la priorité d’appel. L’essai direct et le dernier retour utilisateur confirment le rétablissement des médias ; le microphone et les scénarios prolongés restent à valider.

## 7. Pourquoi conserver le SBC sur la liaison série ?

Le port fonctionne à **921 600 bauds, 8N1**, soit un plafond théorique d’environ **92 160 octets par seconde et par sens**, avant les en-têtes et la journalisation.

| Signal | Débit de données audio, hors protocole |
| --- | --- |
| Voix mono 16 bits à 8 kHz | 16 000 octets/s |
| Voix mono 16 bits à 16 kHz | 32 000 octets/s |
| PCM stéréo 16 bits à 44,1 kHz | 176 400 octets/s |
| PCM stéréo 16 bits à 48 kHz | 192 000 octets/s |
| SBC avec les paramètres actuellement annoncés | Débit variable ; environ 328 à 357 kbit/s au bitpool maximal selon fréquence et mode, soit environ 41 à 45 ko/s |

Le PCM stéréo dépasserait largement le plafond de la liaison. Le SBC tient dans le budget avec une marge pour les en-têtes. Il reste compressé avec pertes : l’absence de réduction en mono ne signifie pas une transmission audio sans perte.

Ces débits sont des calculs à partir des formats et paramètres du projet, pas des mesures de débit ou de qualité réalisées sur une session d’écoute.

## 8. Protocole série

Les quatre types de paquets utilisent un en-tête de **20 octets**, puis une charge utile de **1 à 1 024 octets**.

| Position | Taille | Contenu |
| --- | --- | --- |
| 0 | 8 octets | Signature du type de flux |
| 8 | 2 octets | Longueur de la charge utile, uint16 |
| 10 | 2 octets | Fréquence, uint16 |
| 12 | 4 octets | Séquence, uint32 |
| 16 | 4 octets | Somme FNV-1a, uint32 |
| 20 | Longueur annoncée | Données audio ou message de commande/état |

Tous les entiers sont en **little endian**. La somme couvre la longueur, la fréquence, la séquence et les données ; elle ne couvre pas la signature. C’est un contrôle de corruption, pas une authentification cryptographique.

| Signature | Sens | Charge utile | Fréquence |
| --- | --- | --- | --- |
| `PBAUD01!` | ESP32 → PC | PCM signé 16 bits mono d’appel | 8 000 ou 16 000 |
| `PBMIC01!` | PC → ESP32 | PCM signé 16 bits mono du microphone | 8 000 ou 16 000 |
| `PBSBC01!` | ESP32 → PC | Données SBC compressées | 0, marqueur média |
| `PBCTL01!` | Bidirectionnel | Commande USB de 12 octets ou état JSON version 1 | 0 |

Les charges PCM ont une longueur paire. Les charges SBC peuvent avoir une longueur impaire et une trame SBC peut traverser plusieurs paquets série. Le parseur incrémental PyAV reconstitue le flux. Voix descendante et médias partagent un compteur ; le microphone utilise son compteur côté PC.

Les messages de contrôle ont une séquence nulle et une file d’émission dédiée ; ils ne modifient pas le compteur audio. Les commandes ont le format `opcode:u8, force:u8, adresse:6 octets, challenge:u32` ; les huit opérations sont état, appairer, annuler, approuver, refuser, sélectionner, déconnecter et oublier. L’approbation est liée à l’adresse et au challenge courant. L’état JSON contient la liste, le téléphone sélectionné, les connexions des profils et le compte à rebours. Les boutons de gestion sont désactivés après cinq secondes sans état valide.

Les journaux texte partagent le port descendant. Le firmware verrouille la sortie lors de l’envoi d’un paquet pour éviter l’insertion de texte au milieu des données ; le lecteur sépare ces lignes des paquets et conserve les messages ESP32 reconnus dans le journal, sans y copier les charges audio.

## 9. Tampons, priorités et qualité audio

| Mécanisme | Valeur ou comportement actuel |
| --- | --- |
| File d’émission ESP32 | 24 paquets, charge utile maximale 1 024 octets chacun |
| Tampon de réception UART | 8 192 octets |
| Tampon microphone ESP32 | Allocation de 6 400 octets ; limite logique de 200 ms selon la fréquence |
| Péremption des données micro sur ESP32 | Abandon après 200 ms sans mise à jour |
| Autorisation d’envoi du micro côté PC | Voix d’appel reçue depuis moins de 300 ms |
| File micro côté PC | 5 blocs ; blocs vieux de plus de 100 ms abandonnés à l’envoi |
| Sortie Windows | PCM 16 bits, 48 kHz, 2 canaux |
| Blocs entrée/sortie Windows | 960 échantillons par canal, soit 20 ms à 48 kHz |
| Tampon de lecture PC | Maximum 38 400 octets, soit 200 ms de PCM stéréo à 48 kHz |
| Priorité aux appels | Paquets SBC écartés lorsque l’audio HFP est actif |
| Passage appel/média | Vidage du tampon PC au changement de type de flux |

La limite de 200 ms du tampon PC **n’est pas une mesure de la latence totale**. La latence comprend aussi le téléphone, le Bluetooth, les files de la carte, le transport série, le décodage et Windows.

Les appels utilisent encore une adaptation simple : moyenne de groupes pour réduire la fréquence du micro et répétition des échantillons pour l’écoute. Les médias utilisent le rééchantillonneur de PyAV. Il n’y a pas d’annulation d’écho ajoutée par le projet ; l’usage du casque reste le montage de référence.

## 10. Organisation des fichiers

| Fichier ou dossier | Rôle |
| --- | --- |
| `main/main.c` | Démarrage, NVS, Bluetooth, appairage, UART et activation des profils |
| `main/bt_app_hf.c` | Événements HFP et échanges audio des appels |
| `main/bt_app_media.c` | Profil A2DP, déclaration SBC et transfert des données compressées |
| `main/audio_serial.c` et `.h` | Paquets audio/contrôle, files d’émission et réception du microphone |
| `main/phone_manager.c` et `.h` | Téléphones autorisés, sélection persistante, délais et autorisations audio atomiques |
| `main/pairing_security.c` et `.h` | Comparaison numérique et refus des confirmations automatiques ; adaptateur ESP-IDF 6.1 |
| `main/bt_app_core.c` et `.h` | Tâche applicative et distribution des événements |
| `main/bt_app_pbac.c` et `.h` | Accès au répertoire téléphonique hérité de l’exemple |
| `main/app_hf_msg_set.c` | Commandes HFP héritées ; pas d’interface texte active sur le transport actuel |
| `main/gpio_pcm_config.c` | Routage PCM hérité, hors trajet audio HCI actif |
| `main/Kconfig.projbuild` | Options spécifiques à l’exemple |
| `sdkconfig` | Configuration effective du firmware courant |
| `sdkconfig.defaults` | Valeurs initiales du projet |
| `pc/listen.py` | Parseur série, décodage SBC, écoute Windows et capture micro |
| `pc/tray_app.py` | Application Windows, icône de notification, réglages et gestion des téléphones |
| `pc/phone_control.py` | Encodage des commandes et validation des états USB |
| `pc/requirements.txt` | Dépendances audio Python |
| `pc/requirements-desktop.txt` et `pc/build_windows.ps1` | Dépendances et compilation de l’exécutable Windows |
| `pc/test_phone_control.py`, `pc/test_tray_phones.py`, `pc/test_bridge_lifecycle.py` | Tests des commandes, de l’interface et du transport partagé |
| `pc/test_pairing_adapter.py` | Vérification des signatures SDK et de l’absence d’appels bloquants dans les lecteurs audio |
| `pc/test_firmware_policy.py` | Harnais de la politique C ; ignoré ici faute de compilateur hôte |
| `dist/SmartCon/SmartCon.exe` | Exécutable courant, autonome |
| `build_desktop/hardware-stability.log` | Capture du dernier essai média sur le matériel |
| `pc/test_protocol.py` | Tests des paquets, de la resynchronisation et des conversions voix |
| `pc/test_media.py` | Test d’intégration du décodage SBC fragmenté |
| `pc/README.md` | Guide opérationnel du pont actuel |
| `build_audio_pc/` | Construction et firmware utilisés pour le dernier flash |
| `build_audio_pc/boot_check.log` | Capture de vérification du démarrage après correction |
| `build/`, `build_hci/`, `build_serial/` | Autres répertoires de construction présents ; leur nom ne garantit pas leur contenu actuel |
| `.venv-audio/` | Environnement Python local du lecteur |

## 11. Installation et utilisation

### Utilisation normale avec l’application Windows

Lancer **`dist\SmartCon\SmartCon.exe`**, choisir COM3, le casque et le microphone, puis démarrer le pont. Aucun Python séparé n’est requis pour cet exécutable. Utiliser cette version courante plutôt que les copies intermédiaires de diagnostic.

Pour un nouveau téléphone : ouvrir **Appairer (60 s)** dans l’application, choisir SmartCon dans les réglages Bluetooth de l’iPhone, comparer les deux numéros et approuver sur les deux appareils. La carte ferme l’appairage après réussite ou expiration. Pour les téléphones déjà enregistrés, sélectionner une ligne puis Activer ; le téléphone actuellement appairé a été conservé lors du dernier flash.

Les commandes Déconnecter et Oublier sont distinctes : la première retire la sélection, la seconde supprime l’autorisation et demande la suppression du lien Bluetooth enregistré. Une nouvelle association est nécessaire après oubli. Les changements pouvant interrompre un appel demandent confirmation.

Les réglages sont enregistrés lors du démarrage du pont ou avec Enregistrer. Fermer la fenêtre conserve l’application dans la zone de notification ; utiliser **Quitter** pour libérer COM3 avant de flasher ou de lancer un diagnostic.

### Recréer l’exécutable

```powershell
powershell -ExecutionPolicy Bypass -File .\pc\build_windows.ps1
```

Quitter d’abord l’exécutable s’il est ouvert. Le script utilise `.venv-audio`, installe les dépendances de construction et produit `dist\SmartCon\SmartCon.exe`. Un essai sur un PC Windows sans environnement de développement reste à réaliser.

### Préparer le lecteur en ligne de commande

Depuis PowerShell, dans le répertoire du projet :

```powershell
cd C:\esp\phone_bridge
python -m venv .venv-audio
.\.venv-audio\Scripts\python.exe -m pip install -r pc\requirements.txt
```

La création de l’environnement n’est nécessaire que pour une nouvelle installation. L’installation existante dispose déjà des dépendances relevées dans ce document. Utiliser directement l’exécutable Python évite d’avoir à activer le script PowerShell de l’environnement.

### Compiler et flasher

Ouvrir un terminal où ESP-IDF est initialisé, puis exécuter :

```powershell
cd C:\esp\phone_bridge
idf.py -B build_audio_pc -p COM3 build flash
```

Fermer auparavant le lecteur et tout moniteur série. Le flash normal ne nécessite pas d’effacer toute la mémoire ; les données d’appairage NVS sont conservées. Un effacement global ne fait pas partie de la procédure courante.

### Choisir les périphériques et lancer le pont

```powershell
.\.venv-audio\Scripts\python.exe pc\listen.py --list-devices
.\.venv-audio\Scripts\python.exe pc\listen.py --port COM3 --device 13 --input-device 15
```

Sans indices explicites, le lecteur utilise les périphériques Windows par défaut. Sur l’installation de référence, 13 et 15 correspondent aux périphériques HyperX WASAPI.

Options utiles :

| Option | Effet |
| --- | --- |
| `--no-mic` | Écoute sans ouvrir le flux de capture micro |
| `--mic-gain 2` | Gain micro multiplié par deux ; défaut 1, plage autorisée 0 à 10 |
| `--port COM3` | Port série ; adapter si Windows le renumérote |
| `--baud 921600` | Débit du lecteur, qui doit correspondre à celui du firmware |

Le lecteur en ligne de commande utilise le téléphone déjà autorisé et sélectionné par le firmware ; il n’ouvre pas de fenêtre d’appairage. Approuver d’abord tout nouveau téléphone depuis l’application Windows, puis quitter celle-ci avant de lancer le lecteur. Sur l’iPhone, sélectionner **SmartCon** comme sortie pour l’appel ou le média. Les commandes de lecture et le volume restent pilotés depuis l’iPhone et Windows. `Ctrl+C` arrête le lecteur.

Le PC peut continuer à restituer ses propres applications en parallèle, avec la sortie audio partagée utilisée par cette configuration.

## 12. Validation déjà réalisée

### Construction et flash

Le firmware corrigé a été compilé et flashé sur COM3. La taille d’application mesurée au dernier build est **`0xcef90`**, soit **847 760 octets**, pour une partition application de **1 048 576 octets**. Il reste **200 816 octets**, environ **19 %**, dans cette partition.

Cette marge concerne la flash de la partition application ; elle ne mesure pas la mémoire RAM libre. Le fait que la puce possède 4 Mo physiques n’agrandit pas automatiquement la partition de 1 Mo définie actuellement.

### Tests automatiques

Commande :

```powershell
.\.venv-audio\Scripts\python.exe -m unittest discover -s pc -v
```

Le dernier passage a donné **23 tests réussis**, avec PyAV 17.1.0, et **un groupe C natif ignoré** faute de compilateur hôte Windows x86-64. Le compilateur ESP installé permet de vérifier l’adaptateur et le code généré, mais pas d’exécuter ce harnais natif. Les tests exécutés couvrent notamment :

- la réception de paquets fragmentés et mêlés à des journaux texte ;
- la reprise après corruption d’une charge utile ;
- l’alternance de paquets média et appel, avec fragmentation ;
- la reprise vers un appel après un paquet média corrompu ;
- la duplication correcte des échantillons d’appel vers une sortie stéréo ;
- la construction des paquets microphone et leur somme de contrôle ;
- la conversion micro aux deux fréquences d’appel ;
- le mélange d’un microphone stéréo en mono ;
- la saturation du gain sans débordement numérique ;
- l’encodage puis le décodage d’un flux SBC fragmenté à 44,1 et 48 kHz vers une sortie stéréo 48 kHz ;
- les commandes de contrôle, leurs sommes et la validation des états reçus ;
- le partage du port USB entre audio et commandes, puis sa libération à l’arrêt ;
- la sélection du téléphone, les demandes d’approbation, les états périmés et la confirmation d’interruption d’appel dans Tk ;
- la mise à jour du chemin du démarrage Windows lorsque l’application autorisée est déplacée ;
- la conservation des lignes de journal sans journaliser le contenu audio ;
- les signatures et constantes de l’adaptateur comparées aux en-têtes ESP-IDF réels ;
- l’absence d’appels de fonction potentiellement bloquants dans le code compilé des lecteurs d’autorisation audio.

Le test SBC synthétique vérifie le chemin logiciel du codec, pas la séparation acoustique gauche/droite du casque. Les tests Tk demandent un environnement graphique utilisable ; les tests de compilation demandent un build ESP-IDF configuré. Examiner les tests ignorés avant d’interpréter le bilan. Le harnais C ignoré ne constitue pas une validation exécutée de toute la politique de connexion.

### Vérification sur la carte et retour utilisateur

Le contrôle du 17 octobre avait confirmé le démarrage HFP et l’enregistrement SBC sans boucle de reset pendant dix secondes. Le 18 octobre, après les corrections d’appairage et de stabilité, le firmware courant a été écrit sur COM3 avec vérification des données et redémarrage. Le téléphone enregistré est resté autorisé.

Le diagnostic direct a observé HFP connecté, puis A2DP connecté, le démarrage de lecture et **plus de 2 000 paquets audio valides**. Les compteurs indiquaient **0 perte**, **0 paquet invalide**, **0 erreur SBC** ; le firmware signalait **0 paquet média bloqué**. Aucun appel n’a été nécessaire avant de démarrer les médias après ce flash.

L’utilisateur a confirmé « Music/video plays normally », puis « ok it seems to work fine now ». Ce retour clôt le défaut de média muet et de connexion instable observé pendant cette intervention, dans les limites de l’essai court.

Le diagnostic était en **écoute seule** : l’ouverture du microphone depuis le processus de diagnostic avait échoué avec une erreur MME. Cela ne constitue ni un test réussi ni une conclusion sur le microphone lancé par l’application normale. L’utilisateur avait signalé que les appels semblaient fonctionner, sans avoir testé le micro. Un essai d’appel avec capture réelle reste nécessaire.

La capture est `build_desktop/hardware-stability.log` et ne contient aucun enregistrement audio. Le diagnostic a été arrêté et la disponibilité de COM3 vérifiée. Le lancement de l’exécutable courant, la création du décodeur SBC embarqué et sa fermeture ont également réussi.

## 13. Essais matériels à formaliser

| Essai | Procédure | Résultat à consigner |
| --- | --- | --- |
| Nouvel appairage | Ouvrir la fenêtre de 60 s, comparer et approuver le numéro | Réussite confirmée sur l’iPhone ; répéter et chronométrer si nécessaire |
| Autorisation et sélection | Enregistrer deux téléphones, choisir le premier puis le second | Un seul téléphone peut fournir appels et médias ; ancien téléphone refusé |
| Verrouillage de l’appairage | Essayer hors fenêtre, refuser une demande, annuler et laisser expirer | Aucun appareil non approuvé autorisé ; délais et refus à vérifier explicitement |
| Oubli et redémarrage | Oublier un téléphone puis redémarrer la carte | Autorisation supprimée et choix actif conservé conformément aux commandes |
| Application et démarrage Windows | Enregistrer, quitter, relancer puis ouvrir une nouvelle session Windows | Conservation des périphériques et lancement optionnel depuis le bon exécutable |
| Appel descendant | Appeler la messagerie ou un interlocuteur | Son audible, niveau, coupures et fréquence négociée |
| Microphone montant | Laisser un message puis le réécouter | Intelligibilité, volume et absence de saturation |
| Conversation | Appel de 15 à 30 minutes | Stabilité, voix simultanées, écho et retard perçu |
| Musique stéréo | Piste comportant un test gauche/droite | Canaux distincts et continuité de lecture |
| Pause/reprise | Répéter plusieurs pauses courtes et longues | Reprise propre, absence de données anciennes |
| Musique → appel → musique | Recevoir un appel pendant une lecture | Priorité voix, micro actif pendant l’appel et reprise média |
| Vidéo | Observer un repère visuel et sonore | Décalage estimé et évolution au fil du temps |
| Reconnexion | Éloignement Bluetooth puis retour ; déconnexion/reconnexion | Retour sans redémarrage manuel ou étapes nécessaires |
| USB et veille Windows | Débrancher/rebrancher puis tester veille/réveil | Comportement du lecteur et besoin éventuel de relance |
| Longue durée | Lecture de 1 à 2 heures minimum | Pertes, erreurs SBC, retard croissant, plantages |

Pour chaque essai, noter le modèle d’iPhone, iOS, l’application utilisée, la durée, les statistiques du lecteur et le résultat. Une validation de musique ne vaut pas automatiquement validation des appels ou de toutes les applications vidéo.

## 14. Diagnostic et dépannage

| Symptôme | Vérifications et action |
| --- | --- |
| SmartCon absent | Pour un nouveau téléphone, ouvrir Appairer (60 s) dans l’application ; SmartCon n’est pas découvrable hors fenêtre. Vérifier ensuite l’alimentation et les profils |
| Redémarrages répétés | Relever l’erreur avant `Rebooting...` ; vérifier que le firmware corrigé est flashé ; ne pas attribuer automatiquement le défaut à l’iPhone |
| Accès refusé à COM3 | Quitter SmartCon par son menu de notification, puis fermer `listen.py`, `idf.py monitor` et les autres logiciels série ; le port est exclusif |
| Appairage réussi mais pas de média | Vérifier le téléphone sélectionné, l’état A2DP, SmartCon comme sortie iPhone et l’exécutable courant. Lire les lignes ESP32 et `SBC received/blocked` dans le journal avant de réappairer |
| Échec avant affichage d’un numéro | Vérifier le firmware courant et l’ouverture de la fenêtre ; oublier l’ancien lien sur l’iPhone si nécessaire. L’adaptateur de sécurité est limité à ESP-IDF 6.1 |
| Connexions instables ou média seulement après un appel | Vérifier que le firmware de stabilité du 18 octobre est installé ; conserver le journal de la tentative pour éviter un diagnostic fondé sur le seul état Connecté |
| Son reçu mais casque silencieux | Relever les indices audio, le périphérique choisi et le volume Windows |
| Microphone silencieux | Vérifier le bouton muet, les permissions Windows et l’indice d’entrée ; parler pendant un appel et observer `micro_niveau` |
| Voix trop faible ou saturée | Ajuster `--mic-gain`, puis refaire un enregistrement de messagerie pour contrôler le résultat |
| Paquets invalides ou pertes | Confirmer 921600 bauds aux deux extrémités ; examiner câble, charge système et journaux ; localiser la cause avant de modifier les tampons |
| Erreurs SBC | Vérifier `erreurs_sbc`, les pertes série et la reproductibilité avec une même piste |
| Décalage vidéo | Mesurer d’abord la latence ; aucun réglage audiovisuel calibré n’est actuellement prévu |

L’application conserve ses états Bluetooth et les lignes ESP32 reconnues dans **`%APPDATA%\SmartCon\app.log`**. Pour lire directement la console après avoir quitté l’application et fermé le lecteur :

```powershell
idf.py -B build_audio_pc -p COM3 monitor
```

Déclencher un reset si nécessaire pour voir le démarrage. Quitter le moniteur avec `Ctrl+]` avant de relancer le lecteur. Le moniteur est destiné au diagnostic et peut afficher des données binaires si un flux audio arrive.

### Interpréter les statistiques du lecteur

| Compteur | Signification et limites |
| --- | --- |
| `octets_serie` | Octets lus, y compris les journaux |
| `paquets` | Paquets descendants valides reçus |
| `pertes` | Trous observés dans la séquence ; ils ne désignent pas à eux seuls une perte radio Bluetooth et peuvent inclure des abandons volontaires lors de priorités |
| `invalides` | Candidats de trames rejetés par le parseur |
| `sous-remplissages` | Appels de sortie où il manque du son ; ce compteur augmente aussi pendant les périodes sans lecture |
| `debordements` | Réductions du tampon de lecture pour rester sous sa limite |
| `erreurs_sbc` | Erreurs interceptées pendant le décodage ou l’adaptation du flux média |
| `micro_paquets` | Paquets microphone écrits sur le port série |
| `micro_pertes` | Blocs micro refusés lorsque la file PC est pleine ; ne compte pas toutes les causes possibles d’abandon |
| `micro_niveau` | Crête absolue du dernier bloc micro traité, rapportée à 32768 ; une valeur ancienne peut rester affichée hors appel |

## 15. Limites et points d’attention actuels

**Qualité de la voix.** La conversion de fréquence des appels reste élémentaire. Elle doit être évaluée à l’écoute avant de décider d’un remplacement par un filtre de meilleure qualité.

**Latence et dérive.** Les tampons sont bornés, mais aucun mécanisme fin de synchronisation des horloges ne maintient encore un niveau cible de tampon à long terme. Une dérive peut provoquer des manques ou des abandons périodiques. Son importance n’a pas été mesurée.

**Transitions.** La priorité repose sur l’état de la liaison audio HFP. La reprise de lecture média dépend aussi du comportement de l’iPhone. Il n’existe pas encore de commande applicative pour forcer une reprise universelle.

**Commandes.** Le code conserve des fonctions HFP héritées, mais le lecteur n’expose pas de commandes pour décrocher, raccrocher ou composer. AVRCP est activé comme dépendance dans la pile, sans contrôleur/cible applicatif initialisé pour proposer lecture/pause, métadonnées ou volume absolu.

**Exploitation.** L’application propose la sélection des ports et périphériques, les états, les réglages mémorisés et un lancement Windows optionnel. La reconnexion série après retrait USB reste manuelle : corriger la cause puis redémarrer le pont. Le démarrage dans une nouvelle session Windows et le déploiement sur une machine propre restent à vérifier.

**Mémoire et configuration.** La flash physique de 4 Mo est sous-utilisée par l’image configurée en 2 Mo et la partition application de 1 Mo. Ce n’est pas le défaut ayant causé les redémarrages. Toute modification du partitionnement devra être planifiée avec les données persistantes et le mode de mise à jour souhaité.

**Reproductibilité.** Aucun dépôt Git exploitable n’a été détecté dans le répertoire lors de l’intervention. Les sources, la configuration et les dépendances doivent encore faire l’objet d’un historique et d’une procédure de restauration fiables.

## 16. Appairage, données et accès au répertoire

L’appairage d’un nouveau téléphone attend son initiative, après ouverture depuis l’application d’une **fenêtre de 60 secondes**. Hors fenêtre, les nouveaux appairages ne sont pas approuvés et la carte n’est pas découvrable. La reconnexion du téléphone sélectionné reste possible.

La capacité DisplayYesNo est fournie par l’application PC : comparaison du numéro à six chiffres puis réponse explicite. L’adaptateur de sécurité refuse les confirmations automatiques Just Works sans approbation USB valide ; les anciens modes PIN et saisie de passkey ne sont pas proposés. Cet adaptateur dépend d’API internes Bluedroid et impose ESP-IDF 6.1 tant qu’une migration n’a pas été revue.

Le firmware conserve **jusqu’à six téléphones et un choix actif** en NVS, en plus des clés de liaison enregistrées par Bluetooth. Le nom d’un téléphone est une étiquette, pas une preuve d’identité. La politique vérifie le téléphone sélectionné pour HFP et A2DP, y compris dans les chemins audio. La sélection, la déconnexion et l’oubli sont des commandes distinctes. Les tentatives de connexion sont séquencées ; le changement attend la fermeture des liens précédents.

L’approbation est liée à l’adresse et au challenge courant. Une expiration ou une annulation invalide la demande ; la fenêtre se ferme après authentification réussie. La liste, le choix actif et les clés survivent à un redémarrage normal. Un flash courant conserve ces données ; un effacement global de NVS les supprimerait.

La politique est appliquée sur l’ESP32, même quand l’application est fermée. La liaison USB peut modifier les autorisations : cette version suppose donc un PC et un accès physique USB de confiance. Le fonctionnement avec l’iPhone utilisé est confirmé ; le refus d’un autre téléphone, les expirations et le basculement entre deux appareils restent à tester explicitement.

**Données et PBAP.** Aucun flux audio n’est enregistré sur disque. Le client PBAP hérité reste initialisé dans le firmware, mais la connexion automatique au répertoire après établissement HFP a été retirée. Aucun transfert de contacts n’a été validé pendant cette intervention. Le code et les commandes héritées demeurent présents ; leur suppression ou une option explicite permettrait de réduire davantage le périmètre.

## 17. Pistes d’amélioration

Les pistes ci-dessous sont des propositions à évaluer ; elles ne sont pas déjà réalisées et ne constituent pas des promesses de performance.

| Priorité proposée | Piste | Bénéfice attendu | Vérification avant adoption |
| --- | --- | --- | --- |
| 1 | Exécuter et consigner la matrice d’essais matériels | Disposer d’un état fonctionnel précis | Résultats reproductibles avec versions et compteurs |
| 1 | Ajouter Git et un point de restauration connu | Pouvoir comparer, revenir en arrière et reproduire un build | Reconstruction depuis une copie propre |
| 1 | Retirer ou rendre optionnel le code PBAP encore initialisé | Réduire le périmètre après suppression de sa connexion automatique | Appels et médias fonctionnent sans initialisation PBAP |
| 1 | Ajouter un diagnostic de démarrage réutilisable | Repérer immédiatement boucle de reset et profil non prêt | Reset avec messages attendus et détection d’échec |
| 2 | Mesurer l’occupation RAM et les piles des tâches | Vérifier la marge après ajout des profils | Minimum de mémoire libre et marges de pile en charge |
| 2 | Rééchantillonnage filtré pour les appels | Améliorer la fidélité vocale | Comparaison enregistrée, coût CPU et latence |
| 2 | Suivi du remplissage et correction douce de dérive | Stabiliser les longues sessions | Courbes de tampon et diminution des coupures |
| 2 | Reconnexion série et choix durable des périphériques | Réduire les manipulations après USB/veille | Retrait USB, changement de port et veille/réveil |
| 2 | Valider l’interface et les réglages sur plusieurs sessions Windows | Confirmer les fonctions maintenant implémentées | États fiables, périphériques mémorisés et démarrage optionnel |
| 3 | AVRCP : commandes, métadonnées, volume | Commander les médias depuis le PC | Compatibilité iPhone, cohérence du volume et reconnexion |
| 3 | Commandes d’appel depuis le PC | Décrocher/raccrocher sans manipuler le téléphone | Scénarios d’appels entrants, sortants et rejets |
| 1 | Tester la politique avec deux téléphones et des demandes refusées | Valider les restrictions maintenant implémentées | Basculement, oubli, expiration et refus d’appareils non sélectionnés |
| 3 | Réduire et calibrer la latence média | Améliorer l’usage vidéo | Mesure avant/après, sans hausse des pertes |
| À étudier | Sortie vers un périphérique audio virtuel Windows | Utiliser le son dans d’autres applications | Besoin réel, routage, boucle audio et installation |
| 2 | Valider le paquet Windows autonome sur une machine propre | Vérifier le déploiement sans Python installé | Installation, périphériques audio et nouvelle session Windows |

### Autres architectures possibles

**Conserver l’architecture actuelle** est une base raisonnable pour la prochaine phase : elle utilise le matériel existant, transporte le SBC sans réduction en mono et garde la logique audio lourde sur le PC. Mesurer ses limites permettra de savoir si un changement est nécessaire.

**Transport USB audio natif.** Une autre architecture pourrait présenter un périphérique audio USB au PC, pour éviter le lecteur série. Le CP210x actuel est un pont UART, pas un périphérique audio USB. Cette piste demanderait une conception différente et la vérification conjointe des capacités USB, Bluetooth Classic, HFP et A2DP du matériel envisagé.

**Transport réseau.** Un transfert par Wi-Fi pourrait être étudié pour s’affranchir du câble de données ou transporter d’autres formats. Il ajouterait la gestion réseau, la gigue et des contraintes de coexistence radio sur la carte ; il ne garantit pas une meilleure latence.

**Réception directement par le Bluetooth du PC.** Cette piste pourrait retirer l’ESP32 du montage, mais ses possibilités réelles devraient être vérifiées avec la version Windows, les pilotes et surtout le besoin complet d’appels bidirectionnels. Elle n’est pas validée dans ce projet.

**Autres codecs.** AAC ou un autre traitement pourraient être étudiés séparément. Ils impliqueraient négociation, compatibilité, décodage et essais supplémentaires ; le SBC actuel évite de multiplier ces variables avant la validation de base.

## 18. Prochaine étape proposée

La prochaine vérification est **un appel réel avec le microphone du casque** : laisser un message et le réécouter, ou obtenir le retour d’un interlocuteur sur l’intelligibilité, le niveau et les coupures. Le test média réussi était en écoute seule ; il ne valide pas le trajet montant.

Compléter ensuite la matrice par une conversation prolongée, musique–appel–musique avec micro, pause/reprise, lecture longue, vidéo et reconnexion après veille/USB. Avec un second téléphone, vérifier sélection, refus, expiration et oubli. Consigner les durées, versions et compteurs en complément du retour utilisateur positif.

En parallèle, préparer une sauvegarde versionnée du firmware flashé, de `sdkconfig`, de l’application et de ses dépendances, puis traiter le code PBAP hérité. Conserver les captures avant qu’une nouvelle construction les remplace.

## 19. Références et preuves locales

- [Guide d’utilisation PC](pc/README.md)
- [Firmware de démarrage et Bluetooth](main/main.c)
- [Gestion des appels HFP](main/bt_app_hf.c)
- [Gestion des médias A2DP](main/bt_app_media.c)
- [Transport série et microphone](main/audio_serial.c)
- [Lecteur Windows](pc/listen.py)
- [Application avec icône de notification](pc/tray_app.py)
- [Commandes de gestion des téléphones](pc/phone_control.py)
- [Politique des téléphones autorisés](main/phone_manager.c)
- [Adaptateur de sécurité ESP-IDF 6.1](main/pairing_security.c)
- [Exécutable Windows courant](dist/SmartCon/SmartCon.exe)
- [Script de compilation Windows](pc/build_windows.ps1)
- [Capture du dernier essai média](build_desktop/hardware-stability.log)
- [Accès au répertoire hérité](main/bt_app_pbac.c)
- [Configuration active](sdkconfig)
- [Dépendances Python](pc/requirements.txt)
- [Tests de protocole](pc/test_protocol.py)
- [Test d’intégration SBC](pc/test_media.py)
- [Journal de vérification après correction](build_audio_pc/boot_check.log)

Les journaux et binaires présents dans les répertoires de construction peuvent être remplacés par une prochaine compilation ou une nouvelle capture. Pour conserver la preuve de cet état, les archiver avec une version datée des sources et de la configuration.
