# Bingo musical

Génère des grilles de bingo musical prêtes à imprimer à partir d'une playlist
Spotify :

- un **PDF multipage** (A4, une grille unique par page, case centrale
  « ★ FREE ★ » si la taille est impaire) ;
- un **conducteur animateur** (`.txt`) : tous les morceaux de la playlist dans
  un ordre mélangé, à cocher au fil de la soirée.

## Installation

Python 3.9+ requis.

```bash
python -m venv .venv
source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

## Identifiants Spotify

1. Créez une application sur <https://developer.spotify.com/dashboard>.
2. Récupérez son **Client ID** et son **Client Secret**.

> Les playlists générées par Spotify (« Top 50 », « Daily Mix »…) ne sont plus
> accessibles aux nouvelles applications et renvoient une 404 : utilisez une
> playlist **publique créée par un utilisateur**.

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
| `--client_id` | oui | — | Client ID Spotify |
| `--client_secret` | oui | — | Client Secret Spotify |
| `--output` | non | `bingo_grilles.pdf` | PDF produit |
| `--conductor` | non | `conducteur_animateur.txt` | Conducteur produit |
| `--seed` | non | aléatoire | Graine pour reproduire un tirage |

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
