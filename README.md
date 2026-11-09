# Bingo musical

Génère des grilles de bingo musical prêtes à imprimer à partir d'une ou
plusieurs playlists Spotify, mélangées en un seul répertoire :

- un **PDF multipage** (A4, une grille unique par page, case centrale
  « ★ FREE ★ » si la taille est impaire) ;
- un **conducteur animateur** (`.txt`) : tous les morceaux de la playlist dans
  un ordre mélangé, à cocher au fil de la soirée.

## Installation

Python 3.9+ et spotipy 2.26+ requis (nouvel endpoint de playlist de 2026).

```bash
python -m venv .venv
source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration Spotify (une seule fois)

1. Créez une application sur <https://developer.spotify.com/dashboard>
   (API utilisée : **Web API**).
2. Dans ses réglages, ajoutez la **Redirect URI** exacte :
   `http://127.0.0.1:8888/callback` (Spotify refuse désormais `localhost`).
3. Récupérez son **Client ID** et son **Client Secret**.
4. Si quelqu'un d'autre que le titulaire du compte développeur doit lancer le
   script, ajoutez son compte dans **User Management** (5 utilisateurs maximum
   en mode développement).

Les identifiants peuvent être passés en option, par variables
d'environnement (pour ne pas les laisser dans l'historique du shell) :

```bash
export SPOTIPY_CLIENT_ID="VOTRE_CLIENT_ID"
export SPOTIPY_CLIENT_SECRET="VOTRE_CLIENT_SECRET"
```

ou par un fichier YAML (`--config`), au format du `config.yml` de
[spotify-tidal-sync](https://github.com/Tuxem/spotify-tidal-sync) : seul son
bloc `spotify:` est lu (`client_id`, `client_secret`, `redirect_uri`,
`open_browser`). La même application Spotify sert alors aux deux outils.

```bash
python bingo_musical.py --config ../spotify-tidal-sync/config.yml --playlist "…" --cards 30
```

Ordre de priorité : ligne de commande, puis variables d'environnement, puis
fichier `--config`.

## Authentification

Par défaut (`--auth user`), le script utilise le flux OAuth **Authorization
Code** de l'API développeur, au nom de votre compte Spotify :

- au premier lancement, le navigateur s'ouvre et vous demande d'autoriser
  l'application (lecture seule des playlists, y compris privées et
  collaboratives) ;
- le jeton, avec son *refresh token*, est conservé dans
  `~/.cache/bingo_musical/spotify_token.json` (dossier en `700`) et renouvelé
  automatiquement : les lancements suivants ne demandent plus rien ;
- sur une machine sans écran, `--no_browser` affiche l'URL à ouvrir ailleurs
  et vous demande de coller l'URL de retour ;
- pour vous déconnecter ou changer de compte, supprimez ce fichier de cache ;
- si vous utilisez déjà spotify-tidal-sync avec la même application, son jeton
  (`.cache-<username>` à la racine de ce projet) couvre aussi les droits du
  bingo : `--token_cache ../spotify-tidal-sync/.cache-<username>` évite une
  nouvelle autorisation.

> **Pourquoi la connexion utilisateur ?** Depuis février 2026, une application
> en mode développement n'obtient le contenu d'une playlist que pour un
> utilisateur connecté qui en est **propriétaire ou collaborateur**. Pour une
> playlist d'un autre compte, copiez ses morceaux dans une playlist à vous.
> Les playlists éditoriales ou générées par Spotify (« Top 50 »,
> « Daily Mix »…) restent inaccessibles.
>
> `--auth app` (Client Credentials, sans compte) ne lit le contenu des
> playlists que pour une application en *extended quota mode*.

Le quota d'appels est partagé entre toutes les applications de votre compte
développeur (spotify-tidal-sync compris). Le script relance une requête
limitée (429) si Spotify demande d'attendre au plus une minute ; au-delà
(quota quotidien épuisé, blocage pouvant durer près d'un jour), il s'arrête
en indiquant jusqu'à quand, au lieu de rester figé.

## Utilisation

```bash
python bingo_musical.py \
    --playlist "https://open.spotify.com/playlist/XXXXXXXXXXXXXXXXXXXXXX" \
    --cards 30 \
    --client_id "VOTRE_CLIENT_ID" \
    --client_secret "VOTRE_CLIENT_SECRET"
```

| Option | Obligatoire | Défaut | Rôle |
|---|---|---|---|
| `--playlist` | oui | — | Une ou plusieurs playlists (URL, URI `spotify:playlist:…` ou ID) |
| `--cards` | oui | — | Nombre de grilles uniques |
| `--size` | non | `5` | Taille N d'une grille N x N (2 à 10) |
| `--client_id` | oui* | `$SPOTIPY_CLIENT_ID` | Client ID Spotify |
| `--client_secret` | oui* | `$SPOTIPY_CLIENT_SECRET` | Client Secret Spotify |
| `--config` | non | — | YAML avec un bloc `spotify:` (format spotify-tidal-sync) |
| `--auth` | non | `user` | `user` (OAuth, votre compte) ou `app` (application seule) |
| `--redirect_uri` | non | `http://127.0.0.1:8888/callback` | URI de retour OAuth déclarée dans le tableau de bord |
| `--token_cache` | non | `~/.cache/bingo_musical/spotify_token.json` | Cache du jeton utilisateur |
| `--no_browser` | non | — | Autorisation par copier-coller d'URL |
| `--output` | non | `bingo_grilles.pdf` | PDF produit |
| `--conductor` | non | `conducteur_animateur.txt` | Conducteur produit |
| `--seed` | non | aléatoire | Graine pour reproduire un tirage |

\* sauf si la variable d'environnement correspondante ou `--config` le fournit.

## Plusieurs playlists

Passez plusieurs playlists à la suite, ou répétez `--playlist` :

```bash
python bingo_musical.py --playlist URL_ROCK_80 URL_MARIAGE URL_ANNEES_2000 --cards 40
python bingo_musical.py --playlist URL_ROCK_80 --playlist URL_MARIAGE --cards 40
```

Leurs morceaux forment un seul répertoire, dans lequel chaque grille pioche.
**Un titre n'est gardé qu'une fois**, toutes playlists confondues : la
comparaison porte sur le nom du morceau, sans tenir compte :

- de la casse, des accents et de la ponctuation ;
- de **tout ce qui est entre parenthèses ou crochets**, quel qu'en soit le
  contenu : « Creep (Acoustic) », « Hotel California (2013 Remaster) » et
  « Bohemian Rhapsody [Live Aid] » valent « Creep », « Hotel California » et
  « Bohemian Rhapsody » ;
- des mentions de version après un tiret (« - Remastered 2011 »,
  « - Live », « - Radio Edit »…). Un tiret sans mention de version est gardé,
  car il fait parfois partie du titre.

La première occurrence, dans l'ordre des playlists, est conservée, avec son
libellé d'origine : la normalisation ne sert qu'à comparer, elle ne modifie
pas ce qui est imprimé sur les grilles. Une même playlist
indiquée deux fois n'est lue qu'une fois.

Deux morceaux différents portant le même titre (une reprise, ou « Hello »
d'Adele et de Lionel Richie) sont donc eux aussi fusionnés : c'est voulu, deux
cases « Hello » sur une grille seraient ambiguës pour les joueurs.

Le sous-titre du PDF et l'en-tête du conducteur listent toutes les playlists.
## Règles de génération

- Chaque grille pioche au hasard N² morceaux (N² − 1 si N est impair) ; deux
  grilles n'ont jamais exactement le même ensemble de morceaux.
- Les doublons (même titre, voir ci-dessus), les épisodes de podcast et les
  fichiers locaux sont ignorés.
- Le script s'arrête avec un message clair si la playlist est trop courte pour
  une grille, ou pour le nombre de grilles uniques demandé. Il avertit si elle
  dépasse à peine la taille d'une grille (gagnants simultanés probables).
- Le texte de chaque case est réduit jusqu'à tenir sans déborder.
- Le symbole « ★ » nécessite une police Unicode installée (DejaVu Sans,
  Arial Unicode, Segoe UI Symbol) ; à défaut, la case affiche `* FREE *`.
