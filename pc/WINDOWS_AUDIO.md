# Audio Windows : architecture et maintenance

Ce document décrit le chemin audio de l'application de bureau SmartCon. Le guide
d'utilisation est dans [README.md](README.md) ; les résultats et limites de
validation sont dans [VALIDATION_AUDIO.md](VALIDATION_AUDIO.md).

## Deux sessions sur la même sortie

La lecture audible est un flux PortAudio partagé, stéréo PCM 16 bits à 48 kHz,
catégorie WASAPI **Media**. Les données décodées rejoignent le tampon borné puis
sont copiées par le callback audio. Ce flux reste ouvert pendant tout le
fonctionnement du pont.

Pendant un appel signalé par le firmware, SmartCon ouvre sur le même endpoint
WASAPI une deuxième session de rendu partagée, catégorie **Communications**. Elle
utilise le format de mixage de l'appareil et ne rend que des tampons silencieux.
Cette session temporaire informe Windows de l'état de communication sans
remplacer ni redémarrer le son audible. Un GUID de session neuf est créé à chaque
appel et `NOPERSIST` empêche sa persistance. À la fin, SmartCon arrête et libère
le client WASAPI ; Windows peut alors envoyer la notification de restauration
aux autres sessions.

La session de lecture appelle `IAudioSessionControl2::SetDuckingPreference`
pour que Windows ne réduise pas le propre son du téléphone dans SmartCon. Cette
préférence ne change pas le choix global Windows et ne définit pas le niveau des
autres applications. Le réglage **Communications** de Windows reste maître de
l'atténuation. Le mécanisme est expliqué dans la documentation Microsoft sur
[l'atténuation des flux](https://learn.microsoft.com/en-us/windows/win32/coreaudio/stream-attenuation).

## Choix de périphérique et limites

Dans l'application de bureau, « Périphérique Windows par défaut » est résolu au
démarrage du pont vers le périphérique de sortie par défaut de l'hôte WASAPI.
Une sortie explicitement sélectionnée est conservée. La session de
communication est obtenue à partir de ce même périphérique PortAudio via
`PaWasapi_GetIMMDevice` : ne pas la rediriger vers le périphérique par défaut
quand l'utilisateur en a choisi un autre.

L'atténuation nécessite WASAPI. Une sortie MME, DirectSound ou WDM-KS peut
continuer la lecture normale, mais ne peut pas héberger cette session
complémentaire ; l'interface indique alors que l'atténuation est indisponible.
Les flux que Windows ou une application ne choisit pas d'atténuer, les flux
ouverts pendant un appel et une autre communication encore active relèvent du
comportement Windows. SmartCon ne modifie pas les volumes des autres sessions.

## État d'appel et nettoyage

Seuls les snapshots de contrôle valides du protocole USB mettent à jour l'état
d'appel. La condition est `ready && hfp && call`; l'activité audio, le silence
et la musique A2DP ne déclenchent pas le mode communication. Chaque snapshot
valide rafraîchit son âge. La session est fermée si la condition devient fausse,
si l'état expire après cinq secondes, ou si le pont s'arrête. Des snapshots
répétés entretiennent la session existante et ne la recréent pas.

Les méthodes COM de `CommunicationSession` s'exécutent sur le worker audio,
dans son appartement COM MTA. Cet appartement reste initialisé jusqu'à la
fermeture des flux. Le pointeur `IMMDevice` obtenu depuis PortAudio et le client
audio emprunté dans `protect_playback` ne sont pas libérés par SmartCon. Le client
activé pour la session silencieuse, ainsi que les interfaces obtenues par
`GetService`/`QueryInterface`, sont détenus par SmartCon et libérés avec
`Release`. Toute évolution de ce code doit préserver ces règles, notamment sur
les chemins d'erreur partiels.

Si l'ouverture ou l'entretien de la session silencieuse échoue, SmartCon la
ferme, désactive l'atténuation pour cette exécution du pont et conserve le flux
audible. Si le flux audible ne peut pas s'ouvrir, le pont échoue normalement.
L'arrêt ferme la session de communication avant le flux média.

## Adaptateur WASAPI et version

Les détails ctypes et les appels COM sont isolés dans
[`windows_audio.py`](windows_audio.py). `sounddevice` n'expose pas publiquement
le champ `streamCategory` utilisé pour configurer le flux média ;
`category_settings` contrôle donc la version et la présence du champ au
démarrage. La version `sounddevice==0.5.6` est épinglée dans les dépendances de
bureau. Les signatures COM et les indices des méthodes d'interface doivent être
revérifiés si PortAudio, sounddevice ou les interfaces Windows changent.

Le chemin `desktop_audio` est activé uniquement par l'application Windows. Le
lecteur `pc/listen.py` en ligne de commande garde son ouverture audio précédente
et ne crée pas de session de communication silencieuse.

## Validation

Les tests simulés couvrent les transitions, l'expiration, la déconnexion, les
erreurs et le nettoyage. Le test `test_windows_ducking` est un test Windows
opt-in : `SMARTCON_TEST_AUDIO=1` lui permet de créer un flux WASAPI silencieux
et d'observer les notifications natives DUCK/UNDUCK. Il ne valide pas le son
d'un appel téléphonique ni l'effet de chaque application sur un enregistrement
OBS. Les résultats réellement observés et les essais qui restent à faire sont
consignés dans [VALIDATION_AUDIO.md](VALIDATION_AUDIO.md).
