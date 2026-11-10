# Appels et medias iPhone avec le casque et le micro Windows

Nom du produit et nom Bluetooth : **SmartCon**. Pour appliquer le nouveau nom a
la carte, compiler puis flasher le firmware (`idf.py -B build_audio_pc -p COM3 build flash`).
Si l'iPhone conserve l'ancien nom en cache, oublier l'appareil Bluetooth puis
refaire l'appairage avec SmartCon. Le dossier de travail reste `C:\esp\phone_bridge`.

## Application Windows avec icone pres de l'horloge

Compilation depuis la racine du projet (acces Internet necessaire pour installer
les dependances de construction) :

```powershell
powershell -ExecutionPolicy Bypass -File .\pc\build_windows.ps1
```

Le resultat est `dist\SmartCon\SmartCon.exe`, un fichier autonome qui embarque Python,
PortAudio, PyAV et ses bibliotheques FFmpeg. Aucun Python ni FFmpeg separe ne doit
etre installe sur le PC destinataire. Conserver cet executable a un emplacement
stable avant d'activer le demarrage avec Windows.

Au lancement, la fenetre permet de choisir le port COM, le casque et le micro
(avec leur API audio Windows), puis de demarrer ou arreter le pont. Le premier
lancement utilise COM3 et les peripheriques Windows par defaut. Les reglages sont
enregistres au demarrage du pont ou avec le bouton Enregistrer. Arreter le pont
avant de changer les peripheriques, puis utiliser Actualiser apres un branchement.
Le mode ecoute seule desactive la capture du micro.

Fermer ou masquer la fenetre laisse l'application dans la zone de notification.
Double-cliquer sur l'icone ou utiliser le menu clic droit pour ouvrir les reglages.
Ce menu propose aussi Demarrer, Arreter et Quitter. Quitter ferme les flux audio,
libere le port COM et termine l'application. Une seconde instance est refusee.

L'etat principal indique la connexion USB au pont, l'attente de son, un appel,
une lecture media ou une erreur. Le panneau Telephones affiche separement
les connexions Bluetooth pour les appels (HFP) et les medias (A2DP),
le telephone selectionne et la fenetre d'appairage.
En cas de debranchement ou d'erreur, corriger la cause puis cliquer sur Demarrer.

Les options Demarrer avec Windows et Demarrer le pont a l'ouverture sont
independantes ; cliquer sur Enregistrer pour les appliquer. Le lancement avec
Windows est configure pour l'utilisateur courant, sans droits administrateur,
dans la cle de registre `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
Il ouvre l'application masquee. Decochez l'option puis enregistrez avant de
deplacer ou supprimer l'executable. Aucun demarrage automatique n'est active
sans selection de cette option.

Reglages : `%APPDATA%\SmartCon\settings.json`.
Journal technique avec rotation : `%APPDATA%\SmartCon\app.log`.
Aucun son n'est enregistre. Le micro n'est transmis que pendant les appels.

Pour lancer depuis les sources :

```powershell
.\.venv-audio\Scripts\python.exe -m pip install -r pc\requirements-desktop.txt
.\.venv-audio\Scripts\python.exe pc\tray_app.py
```

Validation manuelle apres compilation : verifier l'icone et son menu, changer
les peripheriques puis relancer pour verifier leur memorisation, demarrer/arreter
un appel et un media, debrancher l'USB et verifier l'erreur, puis Quitter et
verifier que le port COM est disponible pour le flash. Tester aussi une nouvelle
session Windows avec puis sans le demarrage automatique. Le mode `--smoke-test`
ouvre l'icone puis quitte apres une seconde sans ouvrir le pont audio.

## Son séparé dans OBS et Discord

SmartCon joue le son dans son propre processus, sur le casque choisi. Dans
l'application Windows, « Périphérique Windows par défaut » utilise maintenant
la sortie Windows WASAPI par défaut, en mode partagé. Une sortie explicitement
choisie reste inchangée. Le périphérique est résolu au démarrage du pont et reste
le même pendant les passages média/appel ; arrêter puis redémarrer le pont pour
prendre en compte un changement de périphérique par défaut.

Pour choisir si le téléphone est entendu dans OBS :

1. Désactiver **Audio du bureau** dans **Paramètres → Audio** : cette capture
   reprend tous les sons du casque, y compris SmartCon.
2. Ajouter une **Capture audio d'application** pour chaque application à diffuser.
3. Ouvrir la fenêtre SmartCon et l'ajouter comme source audio distincte. Utiliser
   la correspondance par exécutable pour `SmartCon.exe`.
4. Couper ou activer cette source dans le mélangeur OBS. Le son reste audible
   dans le casque. Laisser le monitoring OBS de cette source désactivé pour ne
   pas l'entendre deux fois.

L'image peut rester une capture de l'écran entier : la sélection de l'audio est
indépendante. Vérifier la capture après avoir masqué SmartCon près de l'horloge ;
si OBS ne retrouve pas sa fenêtre, la laisser ouverte ou réduite pendant le stream.
Depuis les sources Python, le processus peut apparaître sous le nom Python :
utiliser l'exécutable distribué pour identifier SmartCon sans ambiguïté.
Voir le [guide OBS](https://obsproject.com/kb/application-audio-capture-guide).

Dans Discord, partager l'application souhaitée avec son audio, puis vérifier
depuis un autre participant que SmartCon n'est pas transmis. Une capture de
**tout le son système** inclut SmartCon : l'application ne propose pas de bouton
permettant de l'en exclure universellement. Aucun câble audio virtuel n'est ajouté.

## Atténuation Windows pendant les appels

La case **Atténuation Windows pendant les appels**, activée par défaut, signale
les appels à Windows. Le bouton **Réglages Windows : Communications** ouvre
l'onglet où choisir une réduction de 50 %, de 80 %, le silence des autres sons
ou **Ne rien faire**. SmartCon ne modifie pas ce réglage global. Arrêter le pont
avant de changer la case, puis le redémarrer ; les préférences sont enregistrées
avec les autres réglages dans `settings.json` (`windows_ducking`).

La baisse commence dès l'état d'appel transmis par le firmware : sonnerie, appel
sortant, conversation ou liaison vocale telle que Siri. Elle ne dépend pas du
niveau sonore : un silence de l'interlocuteur ne la désactive pas. La musique
A2DP du téléphone ne déclenche pas l'atténuation. Le mode écoute seule reste
compatible avec cette fonction.

Le son audible reste dans une session média protégée de l'atténuation. Une
session de communication silencieuse, distincte et temporaire, signale l'appel
à Windows sur le même périphérique. Elle est libérée à la fin de l'appel,
à la déconnexion ou après cinq secondes sans état valide. La sortie audible
n'est pas rouverte pendant ces transitions. Cette séparation évite que Windows
conserve l'état « communication » sur la session utilisée pour les médias.
Il s'agit de sessions internes, pas de nouveaux périphériques audio.
Arrêter ou quitter SmartCon ferme aussi la session de communication. Windows
gère la restauration ; une autre communication active, par exemple Discord,
peut maintenir une atténuation après la fin de l'appel SmartCon.

L'atténuation nécessite une sortie **Windows WASAPI**. Les anciennes sorties MME,
DirectSound ou WDM-KS sont conservées si sélectionnées, avec un message invitant
à choisir leur variante WASAPI. Si l'ouverture ou l'entretien de la session de
communication échoue, SmartCon la libère, affiche **Atténuation indisponible** et
conserve la lecture normale sur la même sortie, sans réessayer jusqu'au prochain
démarrage du pont. Un échec d'ouverture de la sortie audible arrête le pont.

Les limites sont celles de Windows : des applications peuvent gérer elles-mêmes
leur réaction aux communications, et les flux ouverts pendant un appel ne sont
pas nécessairement atténués. Il n'y a pas de curseur ni d'exceptions par
application dans SmartCon. L'effet sur le son capturé par OBS doit être vérifié
avec la méthode de capture choisie ; l'exclusion de SmartCon et l'atténuation
restent deux réglages indépendants.
Voir le [comportement Windows](https://learn.microsoft.com/en-us/windows/win32/coreaudio/stream-attenuation).

Le lecteur `pc/listen.py` en ligne de commande conserve son comportement précédent.
Le firmware et le protocole USB ne changent pas. Le détail de l'architecture
WASAPI, des sessions silencieuses et de leur cycle de vie est documenté dans le
[guide de maintenance audio Windows](WINDOWS_AUDIO.md). `sounddevice` est fixé
à la version 0.5.6 pour son adaptateur WASAPI.

Résultats de construction, tests effectués et essais manuels restants :
[validation audio du 10 novembre 2026](VALIDATION_AUDIO.md).

## Telephones et appairage controle

Mise a jour de stabilite du 18 octobre : les reconnexions attendent que HFP et
le point SBC soient initialises, puis etablissent HFP et A2DP en sequence.
Les demandes en cours sont suivies et les echecs temporises. Activer un telephone
deja selectionne conserve ses liaisons. L'autorisation des donnees audio est
publiee par des valeurs atomiques ; les callbacks audio n'attendent plus le verrou
des commandes ou des ecritures NVS. La fermeture du lien vocal libere aussi
explicitement l'etat micro pour les medias.

Le firmware a ete flashe et les medias testes directement sur la carte avec
l'iPhone deja appaire : plus de 2000 paquets recus, aucune perte ni erreur SBC,
aucun paquet bloque par la politique, et lecture normale confirmee par
l'utilisateur sans appel prealable apres ce flash. Le test utilisait l'ecoute
seule ; le microphone et une conversation restent a verifier. Capture sans
enregistrement audio : `build_desktop/hardware-stability.log`. Le diagnostic
a libere COM3 apres l'essai. La version courante de l'application est
`dist\SmartCon\SmartCon.exe`.

Correctif de l'echec iPhone avant affichage d'un numero : recompiler/flasher le
firmware puis oublier l'ancien lien SmartCon sur l'iPhone avant de recommencer.
L'executable courant avec diagnostics Bluetooth est disponible dans
`dist\SmartCon\SmartCon.exe`. Quitter l'ancienne instance avant de
lancer celui-ci. Le correctif important pour l'appairage est dans le firmware.

ESP-IDF 6.1 peut confirmer Just Works sans remonter de demande a l'application.
`main/pairing_security.c` impose la demande de comparaison numerique et intercepte
ces confirmations automatiques pour les refuser sans approbation USB valide.
Cet adaptateur utilise deux points internes Bluedroid via les options de liaison
`--wrap`; il est limite explicitement a ESP-IDF 6.1 et doit etre revu lors d'une
migration. Le test `test_pairing_adapter.py` compile les signatures et les bits
de securite contre les vrais en-tetes du SDK installe.
Les profils peuvent aussi terminer leur connexion avant le callback GAP
d'authentification : un unique candidat en cours d'appairage est maintenant
maintenu pendant cette phase, avec les deux chemins audio bloques jusqu'a
l'approbation et l'authentification reussies.

Mettre a jour **le firmware et l'application Windows ensemble**. L'ancien firmware
ne comprend pas les commandes de gestion ; les boutons restent alors desactives.
Quitter l'application avant de flasher, puis la relancer et demarrer le pont USB.

1. Cliquer sur **Appairer (60 s)**. Cela deconnecte temporairement le telephone
   actif et ouvre une fenetre d'appairage limitee a 60 secondes sur l'ESP32.
2. Dans les reglages Bluetooth de l'iPhone, choisir **SmartCon**.
3. Comparer le numero a six chiffres affiche dans l'application avec celui
   du telephone. Approuver uniquement si les deux correspondent, et confirmer
   aussi sur l'iPhone. Refuser sinon. Aucun numero n'est accepte automatiquement.
4. Apres authentification reussie, le telephone est enregistre et selectionne,
   puis l'appairage se verrouille immediatement. Le bouton Annuler ou l'expiration
   ferme aussi la fenetre. Sans application ouverte, le delai reste applique
   par l'ESP32. Les modes PIN ancien et saisie de passkey ne sont pas pris en charge.

La carte memorise jusqu'a **six telephones autorises**, mais un seul est actif.
Selectionner une ligne puis **Activer** pour changer de telephone. Le firmware
ferme les deux profils de l'ancien telephone avant d'initier ceux du nouveau.
Les autres telephones restent enregistres mais leurs profils et leurs flux audio
sont refuses. Seul le telephone selectionne peut se reconnecter automatiquement,
y compris apres redemarrage de la carte. Les appels et medias sont controles
separement et leur connexion peut prendre quelques secondes.

**Deconnecter** retire la selection active sans effacer les appairages.
**Oublier** retire l'autorisation et demande la suppression de la cle Bluetooth ;
un nouvel appairage devient necessaire. Si le telephone conserve l'ancien lien,
oublier aussi SmartCon dans ses reglages Bluetooth avant de recommencer.
Les changements pouvant interrompre un appel demandent confirmation.

La liste, le choix actif et les cles Bluetooth sont conserves dans la NVS de
l'ESP32. Changer de PC ne supprime donc pas cette politique. Les noms servent
uniquement d'etiquettes ; la reconnexion utilise l'adresse et le lien Bluetooth
authentifie par les cles de l'appairage. Les anciens appairages automatiques
anterieurs a cette version ne sont pas importes comme autorisations : il faut
oublier SmartCon sur l'iPhone puis l'approuver dans l'application.

La liaison USB donne acces aux commandes de gestion : cette version suppose un
PC et un acces physique USB de confiance. Masquer le nom Bluetooth n'est pas
le controle d'acces ; le firmware refuse les demandes non approuvees et bloque
les donnees des appareils non selectionnes.

Validation materielle encore necessaire : appairage avec comparaison numerique
sur l'iPhone, refus d'un second appareil, expiration/cancel pendant une demande,
reconnexion du telephone selectionne apres reboot, changement entre deux
telephones pour appels et medias, suppression d'un appareil, et interruption
d'un appel seulement apres confirmation. La compilation ne prouve pas ces essais.

Le protocole USB ajoute `PBCTL01!`, avec le meme en-tete de 20 octets et checksum
FNV-1a, frequence et sequence a zero. PC vers carte : charge de 12 octets,
`opcode:u8, force:u8, adresse:6 octets, challenge:u32 little-endian` ; opcodes
1=status, 2=pair, 3=cancel, 4=approve, 5=reject, 6=select, 7=disconnect, 8=forget.
La reponse est un etat JSON version 1 de 1024 octets maximum, sur une file dediee
prioritaire ; elle ne modifie pas les numeros de sequence audio. Une approbation
est liee a l'adresse et au challenge de la demande courante. L'interface desactive
les commandes apres cinq secondes sans etat valide. Fermer normalement le pont
envoie cancel ; en cas de panne USB, le delai firmware reste de 60 secondes.

Tests : `python -m unittest discover -s pc -v`. Les tests du protocole et des
controles Tk n'ouvrent pas le port COM. Les controles Tk sont ignores si Tk
n'est pas disponible. Le harnais C de la politique utilise le vrai
`main/phone_manager.c` avec des API ESP simulees ; il demande un clang Windows
avec cible x86-64 et lld (variable `SMARTCON_CLANG`), et est ignore si seul le
compilateur ESP est installe. Les essais Bluetooth reels restent indispensables.

Le pont transmet les appels dans les deux sens : iPhone -> ESP32 -> casque PC,
et microphone du casque -> USB serie -> ESP32 -> iPhone. Il recoit aussi les medias
Bluetooth A2DP (musique et son des videos) en stereo SBC a 44,1 ou 48 kHz.
Le flux reste compresse sur le port serie, puis PyAV le decode sur le PC et le
reechantillonne a 48 kHz pour Windows. Aucun executable FFmpeg separe n'est requis
avec les roues binaires PyAV. Le bitpool SBC est limite a 53 pour tenir a 921600 bauds.

Depuis PowerShell initialise pour ESP-IDF, dans `C:\esp\phone_bridge` :

```powershell
idf.py -B build_audio_pc -p COM3 build flash
.\.venv-audio\Scripts\python.exe -m pip install -r pc\requirements.txt
.\.venv-audio\Scripts\python.exe pc\listen.py --list-devices
.\.venv-audio\Scripts\python.exe pc\listen.py --port COM3 --device 13 --input-device 15
```

Les indices 13 (sortie HyperX) et 15 (micro HyperX) ont ete detectes sur ce PC.
Verifier les indices avec `--list-devices` apres un changement de peripheriques.
Sans selection explicite, les peripheriques Windows par defaut sont utilises.
Si necessaire, creer `.venv-audio` et installer `pc/requirements.txt`.

Fermer le lecteur et tout moniteur serie avant le flash. Ne pas lancer `idf.py monitor`
pendant l'utilisation : le port serie est exclusif. La console interactive du firmware
est remplacee par la reception binaire du micro ; les commandes texte ne sont plus disponibles.
L'appairage depuis l'iPhone reste disponible et la memoire NVS est conservee.

Approuver d'abord l'iPhone avec le panneau Telephones de l'application Windows.
Le lecteur en ligne de commande peut ensuite utiliser le telephone selectionne ;
il n'ouvre pas d'appairage et ne change pas la selection.
Connecter SmartCon sur l'iPhone, lancer un appel vers la messagerie,
puis selectionner SmartCon dans le menu Audio. Parler dans le micro HyperX,
laisser un message puis le reecouter pour valider le trajet montant.
Le test reel d'intelligibilite et de conversation reste a faire sur le materiel.

Pour les medias, lancer de la musique ou une video et choisir SmartCon dans le
selecteur de sortie audio de l'iPhone. Si ce choix n'apparait pas apres la mise a jour,
oublier SmartCon dans les reglages Bluetooth puis refaire l'appairage pour actualiser
les services. Le nom Bluetooth reste le meme pour les appels et les medias.
Le firmware donne priorite au son HFP et abandonne les paquets medias pendant l'appel.
Le PC vide son tampon a chaque passage appel/media ; le micro n'est transmis que
pendant les appels. Le retour aux medias depend de la reprise de lecture par l'iPhone.
Les boutons lecture/pause, les metadonnees et le volume absolu AVRCP ne sont pas implementes ;
utiliser les commandes de l'iPhone et le volume Windows.

Validation materielle a effectuer : ecoute stereo gauche/droite, pause/reprise,
musique -> appel avec micro -> reprise musique, reconnexion Bluetooth et video.
La latence Bluetooth et les tampons peuvent creer un decalage avec l'image de la video ;
la synchronisation audiovisuelle n'est pas calibree. `erreurs_sbc` compte les erreurs
de decodage ; `pertes` compte les trous dans la sequence serie. Le decodeur est
reinitialise apres une perte, un changement de source ou une pause prolongee.

Le micro est actif par defaut. `--no-mic` permet l'ecoute seule.
`--mic-gain 2` augmente le niveau si necessaire (defaut 1, maximum 10).
Les statistiques toutes les cinq secondes indiquent `micro_paquets`, `micro_pertes`
et `micro_niveau` (crete sur 32768). Si le niveau reste nul en parlant, verifier le
bouton muet du casque et les autorisations micro Windows pour les applications de bureau.
Ctrl+C arrete les flux. Aucun enregistrement audio sur disque n'est effectue.

Le PC ouvre les peripheriques a 48 kHz en mode partage, permettant d'entendre aussi
les autres applications Windows. L'entree mono ou stereo est adaptee automatiquement.
La voix du micro est convertie en mono 8 ou 16 kHz selon les trames de l'appel.
Le micro est transmis seulement lorsque des trames d'appel ont ete recues recemment
(delai 300 ms). Le firmware rejette les frequences differentes de l'appel actif,
vide son tampon aux changements de connexion audio et remplace les manques par du silence.
Les tampons sont bornes pour eviter une accumulation de retard ; les donnees micro
sans mise a jour pendant 200 ms sont abandonnees.

La conversion des appels utilise une moyenne de groupes pour le micro et une repetition des
echantillons pour l'ecoute (mono duplique sur les deux canaux). Les medias utilisent
le reechantillonneur filtre de PyAV. Un meilleur reechantillonnage des appels et une gestion
fine de la derive des horloges restent a faire. Aucun traitement d'annulation d'echo
n'est ajoute ; utiliser le casque.

Format serie a 921600 bauds, 8N1 : magic `PBAUD01!` pour le son recu,
`PBMIC01!` pour le micro envoye, longueur uint16, frequence uint16,
sequence uint32, somme FNV-1a uint32, PCM signe 16 bits mono (maximum 1024 octets).
Tous les nombres sont en little endian. La somme couvre longueur, frequence,
sequence et PCM. Les journaux texte entre les trames de reception sont ignores.
Le firmware se resynchronise apres une trame micro invalide.

Les medias utilisent le meme en-tete avec magic `PBSBC01!`, frequence 0 et une charge
utile SBC brute (1 a 1024 octets, longueur impaire autorisee). Les trames SBC peuvent
traverser plusieurs paquets serie. Les appels et medias partagent un compteur de sequence.
Le champ frequence nul identifie les medias dans le lecteur et interdit l'envoi du micro.
L'implementation utilise l'API codec externe d'ESP-IDF 6.1 :
[documentation A2DP Espressif](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32/api-reference/bluetooth/esp_a2dp.html).

Tests sans dependances externes :

```powershell
python -m unittest discover -s pc -v
```

Les tests de protocole n'ont pas de dependance externe. Le test d'integration SBC
encode puis decode un flux fragmente aux deux frequences ; il est ignore si PyAV
n'est pas installe. Verification du 17 octobre 2026 : compilation ESP32 reussie
dans `build_audio_pc` (20 % de marge dans la partition), dix tests reussis avec
PyAV 17.1.0, y compris le decodage SBC aux deux frequences.
Correction du redemarrage en boucle : l'enregistrement du codec attend maintenant
`ESP_A2D_PROF_STATE_EVT / ESP_A2D_INIT_SUCCESS`, car l'initialisation A2DP est
asynchrone. Firmware flashe sur COM3 ; apres reset, le journal confirme
`Discoverable/connectable request: ESP_OK` et `A2DP SBC endpoint ready`, sans
plantage pendant dix secondes. Capture : `build_audio_pc/boot_check.log`.
Apres correction, l'utilisateur a confirme le retablissement du fonctionnement.
Les essais d'ecoute detailles et prolonges restent a consigner. Voir le
[dossier complet du projet](../ETAT_DU_PROJET.md).
