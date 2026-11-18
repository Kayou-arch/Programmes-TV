# Programme TNT : appli qui se met à jour toute seule

L’appli affiche les programmes des chaînes 1 à 26 de la TNT. Elle propose deux vues : **Maintenant** (ce qui passe, avec une barre de progression) et **Ce soir** (jusqu’à 10 jours à l’avance). En touchant une chaîne, on voit toute sa journée.

Les programmes viennent du guide public XMLTV de xmltvfr.fr. Deux fois par jour, GitHub télécharge ce guide automatiquement et le convertit en petits fichiers. À chaque ouverture, l’appli recharge ces fichiers : elle est donc toujours à jour, sans serveur et gratuitement.

## Mise en place (environ 10 minutes, une seule fois)

1. **Crée un compte gratuit sur github.com**, si tu n’en as pas.
2. **Crée un nouveau dépôt.** Bouton « New repository », nom par exemple `programme-tnt`, en **Public**, puis « Create repository ».
3. **Envoie les fichiers.** Clique sur « uploading an existing file » et glisse tout le contenu du dossier décompressé, y compris les dossiers `.github`, `scripts` et `data`. Valide avec « Commit changes ».
   Sur ordinateur, si le dossier `.github` n’apparaît pas (fichier caché), crée-le à la main : « Add file », puis « Create new file », avec pour nom `.github/workflows/update.yml`, et colles-y le contenu du fichier.
4. **Autorise la mise à jour automatique.** Va dans Settings, puis Actions, puis General. Dans « Workflow permissions », coche **Read and write permissions** et enregistre.
5. **Lance la première mise à jour.** Va dans l’onglet **Actions**, ouvre « Mise à jour des programmes TV », puis clique **Run workflow**. Attends environ 1 minute que le rond devienne vert.
6. **Mets l’appli en ligne.** Va dans Settings, puis Pages. Dans « Source », choisis **Deploy from a branch**, branche `main`, dossier `/ (root)`, puis Save. Après 1 à 2 minutes, l’adresse s’affiche, du type `https://ton-pseudo.github.io/programme-tnt/`.
7. **Ajoute-la sur ton téléphone.** Ouvre l’adresse sur ton téléphone. Sur iPhone : bouton Partager, puis « Sur l’écran d’accueil ». Sur Android : menu ⋮, puis « Ajouter à l’écran d’accueil ». Elle s’ouvre ensuite comme une vraie appli.

## Onglet Streaming (Netflix, Prime Video, Disney+)

- **Choix de la plateforme :** Netflix, Prime Video ou Disney+.
- **Top 10 :** pour Netflix, les chiffres officiels de Netflix France. Pour Prime Video et Disney+, qui ne publient pas de classement, les titres les plus populaires en France selon JustWatch.
- **Nouveaux films, nouvelles séries et saisons :** recoupés entre JustWatch, TVmaze, Wikidata et le Top 10 mondial de Netflix.
- **Affiches :** JustWatch, puis TVmaze, IMDb et, en dernier recours, l’image de la bande-annonce YouTube.
- **Résumés :** en français, traduits automatiquement à chaque mise à jour quand la source est en anglais.
- **Bandes-annonces :** lien direct vers la vidéo YouTube, trouvée avec le titre et l’année, pour les films et séries du streaming et de la TV.
- **Bientôt :** films, séries et nouvelles saisons annoncés sur chaque plateforme dans les semaines à venir.
- **Ma liste :** l’étoile sur un film ou une série l’ajoute à ta liste (gardée sur ton téléphone).
- **Aussi sur :** sur les films et séries diffusés à la TV, les plateformes où ils sont aussi disponibles (abonnement ou gratuit).
- Tout fonctionne sans clé. Une clé TMDB (secret `TMDB_KEY`) reste possible en option.
- Les résultats (bandes-annonces, traductions) sont gardés dans `data/cache.json` : les mises à jour suivantes sont plus rapides.

## Mettre à jour l’appli (un seul fichier)

1. Télécharge le zip de la nouvelle version et renomme-le `mise-a-jour.zip` s’il porte un autre nom.
2. Sur GitHub : Add file, puis Upload files, choisis `mise-a-jour.zip`, puis Commit changes.
3. C’est tout. GitHub installe la nouvelle version, met à jour les programmes, puis supprime le zip (environ 10 minutes).

Seule exception : le fichier `.github/workflows/update.yml` ne peut pas s’installer automatiquement. S’il change, il faut l’envoyer à la main.

## Bon à savoir

- **Fréquence des mises à jour :** chaque nuit et chaque après-midi. Pour forcer une mise à jour : Actions, puis Run workflow.
- **Hors connexion :** l’appli affiche les derniers programmes chargés et le signale.
- **Si la mise à jour s’arrête :** GitHub met en pause les tâches automatiques des dépôts inactifs depuis 60 jours. L’onglet Actions propose alors un bouton pour les réactiver.
- **Si une chaîne reste vide :** son identifiant a peut-être changé dans le guide. Les identifiants sont listés en haut de `scripts/update.py`, dans `CHANNEL_IDS`.
- **Source des données :** guide XMLTV de xmltvfr.fr (projet libre XML-TV-Fr). Merci de ne pas augmenter la fréquence des mises à jour, pour ne pas surcharger ce service gratuit.
