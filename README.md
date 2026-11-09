# Bingo musical

Génère des grilles de bingo musical prêtes à imprimer à partir d'une playlist
Spotify :

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

Les identifiants peuvent être passés en option ou par variables
d'environnement, pour ne pas les laisser dans l'historique du shell :

```bash
export SPOTIPY_CLIENT_ID="VOTRE_CLIENT_ID"
export SPOTIPY_CLIENT_SECRET="VOTRE_CLIENT_SECRET"
```

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
- pour vous déconnecter ou changer de compte, supprimez ce fichier de cache.

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
développeur ; le script relance automatiquement les requêtes limitées (429)
en respectant le délai demandé par Spotify.

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
| `--playlist` | oui | — | URL, URI `spotify:playlist:…` ou ID de la playlist |
| `--cards` | oui | — | Nombre de grilles uniques |
| `--size` | non | `5` | Taille N d'une grille N x N (2 à 10) |
| `--client_id` | oui* | `$SPOTIPY_CLIENT_ID` | Client ID Spotify |
| `--client_secret` | oui* | `$SPOTIPY_CLIENT_SECRET` | Client Secret Spotify |
| `--auth` | non | `user` | `user` (OAuth, votre compte) ou `app` (application seule) |
| `--redirect_uri` | non | `http://127.0.0.1:8888/callback` | URI de retour OAuth déclarée dans le tableau de bord |
| `--token_cache` | non | `~/.cache/bingo_musical/spotify_token.json` | Cache du jeton utilisateur |
| `--no_browser` | non | — | Autorisation par copier-coller d'URL |
| `--output` | non | `bingo_grilles.pdf` | PDF produit |
| `--conductor` | non | `conducteur_animateur.txt` | Conducteur produit |
| `--seed` | non | aléatoire | Graine pour reproduire un tirage |

\* sauf si la variable d'environnement correspondante est définie.

## Règles de génération

- Chaque grille pioche au hasard N² morceaux (N² − 1 si N est impair) ; deux
  grilles n'ont jamais exactement le même ensemble de morceaux.
- Les doublons de la playlist, les épisodes de podcast et les fichiers locaux
  sont ignorés.
- Le script s'arrête avec un message clair si la playlist est trop courte pour
  une grille, ou pour le nombre de grilles uniques demandé. Il avertit si elle
  dépasse à peine la taille d'une grille (gagnants simultanés probables).
- Le texte de chaque case est réduit jusqu'à tenir sans déborder.
- Le symbole « ★ » nécessite une police Unicode installée (DejaVu Sans,
  Arial Unicode, Segoe UI Symbol) ; à défaut, la case affiche `* FREE *`.
