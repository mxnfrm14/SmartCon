# Validation audio — 10 novembre 2026

> **État de la livraison :** les résultats historiques ci-dessous concernent
> l'implémentation qui rouvrait le flux audible pendant les transitions. Le
> correctif courant garde ce flux média ouvert et utilise une session WASAPI
> silencieuse avec un GUID temporaire par appel. Le test natif des notifications
> a validé deux cycles `DUCK → UNDUCK`, mais l'exécutable `dist/SmartCon/SmartCon.exe`
> cité dans l'historique n'a pas été reconstruit avec ce dernier correctif.
> Un appel réel avec le téléphone et une mesure de restauration audible restent
> à effectuer après reconstruction.

Pour le fonctionnement actuel, voir le [guide de maintenance audio Windows](WINDOWS_AUDIO.md).

## Vérifications effectuées

### Correctif de restauration du volume après l'appel

Le retour utilisateur a confirmé que les autres applications restaient trop
basses après le raccrochage et retrouvaient leur volume en quittant SmartCon.
Les journaux montraient pourtant `call=false` et le retour en catégorie média.
Un observateur natif `IAudioVolumeDuckNotification` a reproduit le problème :
le flux média rouvert rejoignait la session Windows encore identifiée comme
communication, ce qui déclenchait à nouveau l'atténuation.

La lecture conserve désormais sa session média. Une session de communication
silencieuse possède un GUID différent à chaque appel, sur le même périphérique,
et est entièrement libérée au raccrochage. La session audible SmartCon est
protégée via `IAudioSessionControl2::SetDuckingPreference` ; les volumes des
autres applications et le réglage global Windows ne sont jamais modifiés.
L'initialisation COM reste faite dans le worker.

Validation : **47 tests sans échec, 1 élément ignoré**, avec
`SMARTCON_TEST_AUDIO=1`. Le nouveau test `test_windows_ducking` observe les
notifications natives sur le casque HyperX : deux cycles donnent chacun
exactement `DUCK → UNDUCK`, sans réactivation après le raccrochage, alors que
la lecture média reste active. Le test utilise du silence, aucun micro ni USB ;
la confirmation auditive pendant un appel réel reste nécessaire.

L'exécutable final `dist/SmartCon/SmartCon.exe` a été reconstruit et son test de
lancement s'est terminé avec le code 0. Journal isolé :
`build_desktop/audio-smoke-unduck/SmartCon/app.log`.

Références : [identité d'une session WASAPI](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclient-initialize)
et [observation des événements d'atténuation](https://learn.microsoft.com/en-us/windows/win32/api/audiopolicy/nf-audiopolicy-iaudiosessionmanager2-registerducknotification).

### Correctif après l'erreur de démarrage WASAPI

L'erreur affichant `WdmSyncIoctl ... Windows WDM-KS` a été reproduite alors que
le périphérique sélectionné était bien le casque WASAPI. Elle survenait quand
PortAudio était initialisé sur le thread principal et le flux démarré sur le
thread du pont sans initialisation COM. Le test initial, exécuté sur le thread
principal, ne couvrait pas ce cas.

`run_bridge` initialise désormais COM sur le thread appelant en mode desktop,
et le libère après fermeture de tous les flux, y compris en cas d'erreur.
Les choix de périphérique n'ont pas été changés pour contourner l'erreur.
Référence : [initialisation COM par thread](https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/nf-combaseapi-coinitializeex).

Après correction : suite de **44 tests sans échec, 1 élément ignoré**, avec
`SMARTCON_TEST_AUDIO=1`. Le nouveau test réel initialise PortAudio sur le thread
principal, puis exécute le vrai `run_bridge` sur un worker ; deux démarrages
successifs avec transitions média/appel/média réussissent sur le casque HyperX.
Seul le transport série est simulé : sortie silencieuse réelle, aucun micro,
aucun accès au téléphone. Les tests COM vérifient aussi les références équilibrées
et les chemins d'erreur. Sans la variable, le test matériel reste ignoré.

Le correctif est livré dans **`dist/SmartCon/SmartCon.exe`**. Sa compilation et
son test de lancement ont réussi (code 0 ; journal
`build_desktop/audio-smoke-fixed/SmartCon/app.log`). Quitter la version encore
ouverte avant de lancer cet exécutable. Le fichier de la première livraison
dans `dist/SmartCon-update` est obsolète.

```powershell
$env:SMARTCON_TEST_AUDIO = '1'
.\.venv-audio\Scripts\python.exe -m unittest discover -s pc -v
Remove-Item Env:SMARTCON_TEST_AUDIO
```

### Première validation (avant ce correctif)

| Vérification | Résultat |
| --- | --- |
| `python -m unittest discover -s pc -v` dans `.venv-audio` | Suite de 40 tests sans échec ; 1 élément ignoré : harnais C de politique firmware, faute de clang ciblant Windows. |
| Transitions avec périphériques simulés | Média → communication → média ; états répétés ; silence ; expiration après 5 s ; perte HFP ; firmware non prêt ; arrêt ; erreur USB. |
| Échecs audio simulés | Fermeture du flux dont le démarrage échoue ; retour à la lecture normale après refus du mode communication ; absence de boucle de réessai ; arrêt si la reprise échoue. |
| Compatibilité | Ancien lecteur CLI ; anciens réglages ; sortie explicite conservée ; avertissement pour sortie non WASAPI ; option désactivée ; appel en écoute seule. |
| Sortie WASAPI réelle | HyperX Virtual Surround Sound : ouverture média, réouverture communication, retour média et fermeture réussis. Test silencieux, sans USB ni micro, dans le processus Python. |
| Dépendances | `pip check` réussi ; sounddevice 0.5.6, PortAudio 19.7.0-devel. |
| Construction | PyInstaller réussi vers `dist/SmartCon-update/SmartCon.exe`. |
| Test de l'exécutable | `--smoke-test` terminé avec code 0 : Tk, icône, décodeur SBC et adaptateur de catégories WASAPI chargés. |
| Diff des fichiers PC suivis | `git diff --check -- pc` sans erreur. |

Le test WASAPI réel prouve l'ouverture des catégories sur ce casque ; il ne mesure
pas la réduction de volume d'une autre application et ne valide pas un appel.
Le test de lancement ne capture aucun son et n'ouvre pas le pont USB.

L'exécutable précédent était ouvert et verrouillait
`dist/SmartCon/SmartCon.exe`. Il est resté en place. Pour essayer la mise à jour,
quitter SmartCon depuis son menu près de l'horloge, puis lancer
`dist/SmartCon-update/SmartCon.exe`. Aucun flash de l'ESP32 n'est nécessaire.

Le test de lancement a utilisé un dossier APPDATA isolé dans
`build_desktop/audio-smoke`. Son journal se trouve dans
`build_desktop/audio-smoke/SmartCon/app.log` et contient
`Smoke test completed: Tk, tray, SBC decoder, WASAPI category adapter`.

## Essais restant à effectuer avec le téléphone et les logiciels de diffusion

Ces essais ne sont pas déclarés validés par les tests automatisés :

| Scénario | Résultat attendu |
| --- | --- |
| Musique du téléphone, sans appel | Écoute normale, aucune atténuation déclenchée par SmartCon. |
| Autre application déjà en lecture ; appel entrant puis refus | Baisse dès la sonnerie selon le choix Windows, puis restauration. |
| Appel sortant et conversation, avec périodes de silence | Baisse maintenue pendant l'appel, volume du téléphone conservé. |
| Fin d'appel puis reprise A2DP | Restauration des autres sons, reprise de la musique selon l'iPhone. |
| Siri / autre liaison vocale HFP | Même signal de communication que pour un appel ; retour média à la fin. |
| Appel en écoute seule | Atténuation identique sans capture du microphone. |
| Débrancher l'USB ou quitter SmartCon pendant un appel | Libération du flux de communication ; restauration par Windows en l'absence d'autre communication. |
| Discord en communication simultanée | Pas de volume modifié directement par SmartCon ; Windows peut maintenir l'atténuation liée à Discord. |
| Réglage Windows « Ne rien faire » | Aucune baisse, même si SmartCon indique que l'appel est signalé à Windows. |
| OBS, capture SmartCon par application | Source isolée audible dans l'enregistrement ; bouton muet OBS sans effet sur le casque ; absence de doublon via Audio du bureau. |
| OBS, fenêtre SmartCon masquée | Vérifier la continuité de la capture ; sinon garder la fenêtre ouverte ou réduite et consigner le comportement de la version OBS utilisée. |
| OBS pendant un appel | Écouter l'enregistrement pour établir l'effet réel de l'atténuation Windows sur chaque source capturée. |
| Discord, partage d'une autre application | Un autre participant entend l'application partagée et n'entend pas le téléphone. |

La capture globale du son système reste hors de la garantie d'exclusion de SmartCon.
Les flux ouverts pendant l'appel et les applications qui gèrent elles-mêmes
l'atténuation restent soumis au comportement natif de Windows.
