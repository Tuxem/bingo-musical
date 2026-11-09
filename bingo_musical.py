#!/usr/bin/env python3
"""
Générateur de grilles de BINGO MUSICAL à partir d'une playlist Spotify.

Produit :
  1. un PDF multipage prêt à imprimer (une grille unique par page) ;
  2. un conducteur .txt pour l'animateur (tous les morceaux, ordre mélangé).

Exemple (une ou plusieurs playlists, mélangées en un seul répertoire) :
    python bingo_musical.py \
        --playlist "https://open.spotify.com/playlist/AAAAAAAAAAAAAAAAAAAAAA" \
                   "https://open.spotify.com/playlist/BBBBBBBBBBBBBBBBBBBBBB" \
        --cards 30 --size 5 \
        --client_id "VOTRE_CLIENT_ID" --client_secret "VOTRE_CLIENT_SECRET"

Authentification (--auth) :
  - user (défaut) : flux OAuth « Authorization Code » de l'API développeur.
    Au premier lancement, le navigateur s'ouvre pour connecter votre compte
    Spotify ; le jeton (avec refresh token) est ensuite conservé en cache et
    renouvelé automatiquement. Depuis février 2026, une application en mode
    développement n'obtient le contenu d'une playlist que pour un utilisateur
    connecté qui en est propriétaire ou collaborateur.
  - app : « Client Credentials », sans compte utilisateur. Ne lit le contenu
    des playlists que si l'application est en « extended quota mode ».

Dépendances : pip install spotipy reportlab
"""

from __future__ import annotations

import argparse
import math
import os
import random
import re
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #

FREE_LABEL = "★\u00a0FREE\u00a0★"  # espaces insécables : une seule ligne
FREE_LABEL_ASCII = "*\u00a0FREE\u00a0*"  # repli si aucune police ne contient « ★ »
MIN_SIZE, MAX_SIZE = 2, 10
MAX_UNIQUE_ATTEMPTS = 1000  # tirages max pour obtenir une grille inédite
MAX_RETRY_AFTER = 60  # au-delà (en s), on abandonne plutôt que d'attendre Spotify

# OAuth utilisateur : lecture seule des playlists (y compris privées / collaboratives).
SPOTIFY_SCOPES = "playlist-read-private playlist-read-collaborative"
# Spotify n'accepte plus « localhost » : il faut une IP de bouclage explicite.
# Cette URI doit être déclarée à l'identique dans le tableau de bord développeur.
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"
QUOTA_MESSAGE = ("quota de l'API Spotify dépassé (429). Ce quota est partagé entre "
                 "toutes les applications de votre compte développeur.")
DEFAULT_TOKEN_CACHE = Path.home() / ".cache" / "bingo_musical" / "spotify_token.json"

# Polices TrueType connues contenant « ★ » (U+2605) — Linux, macOS, Windows.
UNICODE_FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf",
     "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", None),
    ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", None),
    ("C:/Windows/Fonts/seguisym.ttf", None),
    ("C:/Windows/Fonts/arialuni.ttf", None),
]


# --------------------------------------------------------------------------- #
# Ligne de commande
# --------------------------------------------------------------------------- #

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Génère des grilles de bingo musical (PDF) depuis une playlist Spotify.",
    )
    parser.add_argument("--playlist", required=True, nargs="+", action="extend",
                        metavar="PLAYLIST",
                        help="URL (ou URI / ID) d'une ou plusieurs playlists Spotify, "
                             "séparées par des espaces ou en répétant --playlist. "
                             "Les morceaux sont mélangés, chaque titre n'est gardé qu'une fois.")
    parser.add_argument("--cards", required=True, type=int,
                        help="Nombre de grilles uniques à générer.")
    parser.add_argument("--size", type=int, default=5,
                        help="Taille de la grille (N pour N x N). Défaut : 5.")
    # Identifiants : ligne de commande, sinon variables d'environnement
    # (SPOTIPY_CLIENT_ID / SPOTIPY_CLIENT_SECRET), sinon fichier --config.
    parser.add_argument("--client_id", default=None,
                        help="Client ID Spotify (ou SPOTIPY_CLIENT_ID, ou --config).")
    parser.add_argument("--client_secret", default=None,
                        help="Client Secret Spotify (ou SPOTIPY_CLIENT_SECRET, ou --config).")
    parser.add_argument("--config", default=None,
                        help="Fichier YAML contenant un bloc « spotify: » (client_id, "
                             "client_secret, redirect_uri, open_browser) — le même format "
                             "que le config.yml de spotify-tidal-sync.")
    # Authentification
    parser.add_argument("--auth", choices=("user", "app"), default="user",
                        help="user : connexion de votre compte Spotify (OAuth, défaut) ; "
                             "app : identifiants de l'application seuls.")
    parser.add_argument("--redirect_uri", default=None,
                        help=f"URI de redirection OAuth, déclarée dans le tableau de bord "
                             f"Spotify. Défaut : {DEFAULT_REDIRECT_URI}")
    parser.add_argument("--token_cache", default=str(DEFAULT_TOKEN_CACHE),
                        help=f"Fichier de cache du jeton utilisateur. Défaut : {DEFAULT_TOKEN_CACHE}")
    parser.add_argument("--no_browser", action="store_true",
                        help="N'ouvre pas le navigateur : affiche l'URL d'autorisation et "
                             "demande de coller l'URL de retour (machine sans écran).")
    # Options supplémentaires (facultatives)
    parser.add_argument("--output", default="bingo_grilles.pdf",
                        help="Fichier PDF de sortie. Défaut : bingo_grilles.pdf")
    parser.add_argument("--conductor", default="conducteur_animateur.txt",
                        help="Fichier texte du conducteur. Défaut : conducteur_animateur.txt")
    parser.add_argument("--seed", type=int, default=None,
                        help="Graine aléatoire (pour reproduire exactement un tirage).")
    args = parser.parse_args(argv)

    # Fusion des sources : ligne de commande > environnement > fichier > défaut.
    conf = load_spotify_config(args.config, parser) if args.config else {}
    args.client_id = (args.client_id or os.environ.get("SPOTIPY_CLIENT_ID")
                      or conf.get("client_id"))
    args.client_secret = (args.client_secret or os.environ.get("SPOTIPY_CLIENT_SECRET")
                          or conf.get("client_secret"))
    args.redirect_uri = (args.redirect_uri or os.environ.get("SPOTIPY_REDIRECT_URI")
                         or conf.get("redirect_uri") or DEFAULT_REDIRECT_URI)
    if conf.get("open_browser") is False:
        args.no_browser = True
    for name in ("client_id", "client_secret"):
        if not getattr(args, name):
            parser.error(f"--{name} manquant : passez-le en option, par la variable "
                         f"SPOTIPY_{name.upper()} ou dans le bloc « spotify: » de --config.")

    if args.cards < 1:
        parser.error("--cards doit être un entier strictement positif.")
    if not MIN_SIZE <= args.size <= MAX_SIZE:
        parser.error(f"--size doit être compris entre {MIN_SIZE} et {MAX_SIZE}.")
    return args


def load_spotify_config(path: str, parser: argparse.ArgumentParser) -> dict:
    """Lit le bloc « spotify: » d'un fichier YAML (format de spotify-tidal-sync)."""
    try:
        import yaml
    except ImportError:
        parser.error("--config nécessite PyYAML : pip install pyyaml")
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except OSError as exc:
        parser.error(f"impossible de lire {path} : {exc}")
    except yaml.YAMLError as exc:
        parser.error(f"{path} n'est pas un YAML valide : {exc}")
    block = data.get("spotify") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        parser.error(f"{path} ne contient pas de bloc « spotify: ».")
    return block


def fail(message: str, code: int = 1) -> None:
    """Affiche une erreur claire sur stderr et quitte proprement."""
    print(f"❌ Erreur : {message}", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------- #
# 1. Récupération des morceaux Spotify
# --------------------------------------------------------------------------- #

def extract_playlist_id(playlist: str) -> str:
    """Accepte une URL open.spotify.com, une URI spotify:playlist:… ou un ID brut."""
    match = re.search(r"playlist[/:]([A-Za-z0-9]{22})", playlist)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{22}", playlist.strip()):
        return playlist.strip()
    fail(f"URL de playlist Spotify invalide : {playlist!r}")
    return ""  # inatteignable, pour les vérificateurs de type


# Tout ce qui est entre parenthèses ou crochets est ignoré pour comparer deux
# titres : « (Remastered 2011) », « [Live at Wembley] », « (Acoustic Version) »,
# « (feat. X) »… quel qu'en soit le contenu.
_BRACKETED = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
_UNCLOSED = re.compile(r"\s*[(\[].*$")  # « Titre (Live » tronqué par Spotify
# Après un tiret, seules les mentions de version sont retirées : le tiret fait
# parfois partie du vrai titre (« Ob-La-Di », « Hey - Ho »…).
_VERSION_WORDS = (r"remaster\w*|live|version|edit|mix|remix|mono|stereo|feat\.?|ft\.?|"
                  r"featuring|acoustic|acoustique|deluxe|bonus|radio|single|demo|instrumental|"
                  r"unplugged|extended|original|bande originale|from\b|soundtrack")
_VERSION_DASH = re.compile(rf"\s+-\s+.*\b(?:{_VERSION_WORDS}).*$", re.IGNORECASE)


def _simplify(text: str) -> str:
    """Casse, accents et ponctuation retirés."""
    t = unicodedata.normalize("NFKD", text.casefold())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^\w]+", " ", t).strip()


def normalize_title(title: str) -> str:
    """
    Clé de dédoublonnage d'un morceau : son TITRE, sans casse, accents,
    ponctuation, ni rien de ce qui est entre parenthèses / crochets, ni mention
    de version après un tiret. « Bohemian Rhapsody - Remastered 2011 »,
    « Bohémian rhapsody (Live) » et « Bohemian Rhapsody [Acoustic] » donnent
    la même clé. Le libellé imprimé sur les grilles, lui, reste intact.
    """
    t = title
    while True:  # de l'intérieur vers l'extérieur : « (Live (2011)) »
        stripped = _BRACKETED.sub(" ", t)
        if stripped == t:
            break
        t = stripped
    t = _VERSION_DASH.sub("", _UNCLOSED.sub("", t))
    # Titre entièrement entre parenthèses (« (Untitled) ») : on garde son contenu.
    return _simplify(t) or _simplify(title) or title.casefold().strip()


def merge_tracks(sources: list[list[tuple[str, str]]]) -> tuple[list[str], int]:
    """
    Fusionne les morceaux de plusieurs playlists, (libellé, titre) chacun.
    Un titre déjà vu (même nom, cf. normalize_title) n'est gardé qu'une fois :
    la première occurrence l'emporte, dans l'ordre des playlists.
    Renvoie (libellés retenus, nombre de doublons écartés).
    """
    seen: set[str] = set()
    merged: list[str] = []
    duplicates = 0
    for source in sources:
        for label, title in source:
            key = normalize_title(title)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            merged.append(label)
    return merged, duplicates


def build_spotify_client(args: argparse.Namespace):
    """Construit le client spotipy selon le mode d'authentification choisi."""
    import spotipy
    from spotipy.cache_handler import CacheFileHandler
    from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth

    if args.auth == "app":
        auth_manager = SpotifyClientCredentials(client_id=args.client_id,
                                                client_secret=args.client_secret)
    else:
        # Le jeton contient un refresh token : on le range hors du dossier courant,
        # dans un répertoire lisible par vous seul.
        cache = Path(args.token_cache).expanduser()
        cache.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache.parent.chmod(0o700)
        except OSError:
            pass  # systèmes de fichiers sans permissions POSIX (Windows…)
        auth_manager = SpotifyOAuth(
            client_id=args.client_id,
            client_secret=args.client_secret,
            redirect_uri=args.redirect_uri,
            scope=SPOTIFY_SCOPES,
            cache_handler=CacheFileHandler(cache_path=str(cache)),
            open_browser=not args.no_browser,
        )

    return spotipy.Spotify(auth_manager=auth_manager, requests_timeout=15,
                           requests_session=build_requests_session())


class SpotifyRateLimitError(Exception):
    """Spotify demande d'attendre plus longtemps que ce qu'on accepte."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(retry_after)


def build_requests_session():
    """
    Session HTTP qui relance les 429 / 5xx en respectant Retry-After, mais
    abandonne si Spotify demande d'attendre plus de MAX_RETRY_AFTER secondes.
    spotipy, lui, attendrait sagement : une application en mode développement
    qui a épuisé son quota quotidien peut être bloquée près d'un jour, et le
    script resterait figé tout ce temps (même garde-fou que spotify-tidal-sync).
    """
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    class FailFastRetry(Retry):
        def get_retry_after(self, response):
            retry_after = super().get_retry_after(response)
            if retry_after is not None and retry_after > MAX_RETRY_AFTER:
                header = response.headers.get("Retry-After", "").strip()
                raise SpotifyRateLimitError(int(header) if header.isdigit() else retry_after)
            return retry_after

    retry = FailFastRetry(total=3, connect=None, read=False, status=3,
                          backoff_factor=0.5,
                          status_forcelist=(429, 500, 502, 503, 504),
                          allowed_methods=frozenset(["GET", "POST"]))
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def read_playlist(sp, playlist_id: str, me: dict | None,
                  access_hint: str) -> tuple[str, list[tuple[str, str]]]:
    """Lit une playlist : (nom, [(« Artiste - Titre », titre), …])."""
    meta = sp.playlist(playlist_id)
    name = meta.get("name") or playlist_id

    if me is not None:
        owner_id = (meta.get("owner") or {}).get("id")
        if owner_id != me["id"] and not meta.get("collaborative"):
            print(f"⚠️  « {name} » appartient à « {owner_id} », pas à vous : "
                  f"son contenu risque d'être refusé. {access_hint}", file=sys.stderr)

    # La pagination est gérée par sp.next() (100 morceaux par page).
    page = sp.playlist_items(playlist_id, additional_types=("track",), limit=100)
    if page is None or "items" not in page:
        fail(f"Spotify n'a pas renvoyé le contenu de « {name} ». {access_hint}")

    entries: list[tuple[str, str]] = []
    while page:
        for entry in page.get("items", []):
            # « item » (nommage depuis 2026) ou « track » (historique).
            track = entry.get("item") or entry.get("track")
            # On ignore les entrées vides, locales ou les épisodes de podcast.
            if not track or track.get("type") != "track" or not track.get("name"):
                continue
            artists = ", ".join(a["name"] for a in track.get("artists", []) if a.get("name"))
            label = f"{artists} - {track['name']}" if artists else track["name"]
            entries.append((label, track["name"]))
        page = sp.next(page) if page.get("next") else None
    return name, entries


def fetch_playlists_tracks(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    """
    Lit toutes les playlists demandées et fusionne leurs morceaux.
    Renvoie (noms des playlists, liste « Artiste - Titre » sans titre en double).
    """
    try:
        import spotipy
    except ImportError:
        fail("la bibliothèque 'spotipy' est absente. Lancez : pip install -r requirements.txt")

    # Une même playlist passée deux fois n'est lue qu'une fois (ordre conservé).
    playlist_ids = list(dict.fromkeys(extract_playlist_id(p) for p in args.playlist))
    sp = build_spotify_client(args)
    access_hint = ("Spotify ne livre le contenu d'une playlist qu'à son propriétaire "
                   "ou à un collaborateur (applications en mode développement). "
                   "Connectez-vous avec le compte propriétaire, ou copiez les morceaux "
                   "dans une playlist à vous.")

    names: list[str] = []
    sources: list[list[tuple[str, str]]] = []
    current = playlist_ids[0]  # playlist en cours, pour situer une erreur
    try:
        me = None
        if args.auth == "user":
            # Déclenche la connexion OAuth au premier lancement (puis cache).
            me = sp.current_user()
            print(f"   Connecté en tant que {me.get('display_name') or me['id']}.")

        for current in playlist_ids:
            name, entries = read_playlist(sp, current, me, access_hint)
            names.append(name)
            sources.append(entries)
            print(f"   « {name} » : {len(entries)} morceau(x).")
    except spotipy.oauth2.SpotifyOauthError as exc:
        hint = ""
        if "redirect" in str(exc).lower():
            hint = (f" — déclarez exactement « {args.redirect_uri} » dans les Redirect URIs "
                    f"de votre application (developer.spotify.com/dashboard).")
        fail(f"authentification Spotify refusée : {exc}{hint}")
    except spotipy.SpotifyException as exc:
        where = f"playlist {current} : "
        if exc.http_status == 429:
            fail(QUOTA_MESSAGE)
        if exc.http_status == 403:
            fail(f"{where}accès refusé par Spotify (403) : {exc.msg}. {access_hint} "
                 f"Si votre compte n'est pas celui du développeur, ajoutez-le dans "
                 f"« User Management » de l'application.")
        if exc.http_status == 404:
            fail(f"{where}introuvable (404) : vérifiez l'URL. Les playlists éditoriales "
                 f"ou générées par Spotify ne sont pas accessibles aux applications "
                 f"en mode développement.")
        fail(f"{where}l'API Spotify a répondu {exc.http_status} : {exc.msg}")
    except SpotifyRateLimitError as exc:
        fail(f"{QUOTA_MESSAGE} Spotify refuse les requêtes pendant encore "
             f"{timedelta(seconds=int(exc.retry_after))} (jusqu'à "
             f"{datetime.now() + timedelta(seconds=exc.retry_after):%d/%m à %H:%M}).")
    except (KeyboardInterrupt, EOFError):
        fail("connexion Spotify annulée.")
    except Exception as exc:  # réseau, timeout…
        fail(f"impossible de joindre Spotify : {exc}")

    tracks, duplicates = merge_tracks(sources)
    if duplicates:
        print(f"   {duplicates} doublon(s) écarté(s) (même titre, toutes playlists confondues).")
    return names, tracks


# --------------------------------------------------------------------------- #
# 2. Génération des grilles
# --------------------------------------------------------------------------- #

def songs_per_card(size: int) -> int:
    """Nombre de morceaux par grille (la case centrale est FREE si size est impair)."""
    return size * size - (1 if size % 2 == 1 else 0)


def check_feasibility(n_tracks: int, size: int, cards: int) -> None:
    """Vérifie qu'il y a assez de morceaux, et assez de combinaisons pour l'unicité."""
    needed = songs_per_card(size)
    if n_tracks < needed:
        fail(f"la playlist ne contient que {n_tracks} morceau(x) distinct(s), "
             f"or une grille {size}x{size} en demande {needed}. "
             f"Ajoutez des morceaux ou réduisez --size.")
    # Deux grilles sont « identiques » si elles contiennent le même ensemble de
    # morceaux : on compte donc les combinaisons C(n, k).
    if math.comb(n_tracks, needed) < cards:
        fail(f"seulement {math.comb(n_tracks, needed)} grille(s) unique(s) possible(s) "
             f"avec {n_tracks} morceaux en {size}x{size} ; {cards} demandée(s).")
    if n_tracks < needed * 1.5:
        print(f"⚠️  Attention : {n_tracks} morceaux pour {needed} cases par grille — "
              f"les grilles se ressembleront beaucoup (gagnants simultanés probables).",
              file=sys.stderr)


def generate_cards(tracks: list[str], size: int, cards: int,
                   rng: random.Random) -> list[list[list[str | None]]]:
    """
    Génère `cards` grilles uniques.
    Chaque grille est une matrice size x size ; `None` désigne la case FREE.
    """
    needed = songs_per_card(size)
    center = size // 2 if size % 2 == 1 else None
    used_sets: set[frozenset[str]] = set()
    result = []

    for card_no in range(1, cards + 1):
        for _ in range(MAX_UNIQUE_ATTEMPTS):
            picked = rng.sample(tracks, needed)  # tirage sans remise, déjà mélangé
            signature = frozenset(picked)
            if signature not in used_sets:
                used_sets.add(signature)
                break
        else:
            fail(f"impossible de produire une grille n°{card_no} inédite après "
                 f"{MAX_UNIQUE_ATTEMPTS} essais. Réduisez --cards ou agrandissez la playlist.")

        cells = iter(picked)
        grid = [[None if (r == center and c == center) else next(cells)
                 for c in range(size)] for r in range(size)]
        result.append(grid)
    return result


# --------------------------------------------------------------------------- #
# 3. Export PDF (ReportLab)
# --------------------------------------------------------------------------- #

def register_fonts() -> tuple[str, str, bool]:
    """
    Enregistre une police Unicode si possible (pour afficher « ★ »).
    Renvoie (police normale, police grasse, unicode_ok).
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for regular, bold in UNICODE_FONT_CANDIDATES:
        if not Path(regular).is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont("BingoSans", regular))
            bold_name = "BingoSans"
            if bold and Path(bold).is_file():
                pdfmetrics.registerFont(TTFont("BingoSans-Bold", bold))
                bold_name = "BingoSans-Bold"
            return "BingoSans", bold_name, True
        except Exception:
            continue
    # Repli : polices standard PDF (pas de « ★ », remplacée par « * »).
    return "Helvetica", "Helvetica-Bold", False


def fit_paragraph(text: str, style, width: float, height: float,
                  max_size: float, min_size: float = 5):
    """
    Construit un Paragraph dont la taille de police est réduite jusqu'à ce que
    le texte tienne dans la cellule (largeur ET hauteur), sans déborder.
    """
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    font_size = max_size
    while True:
        st = ParagraphStyle(f"fit{font_size}", parent=style,
                            fontSize=font_size, leading=font_size * 1.15)
        para = Paragraph(text, st)
        _, h = para.wrap(width, height)
        # On vérifie aussi qu'aucun mot isolé n'est plus large que la cellule.
        too_wide = para.minWidth() > width
        if (h <= height and not too_wide) or font_size <= min_size:
            return para
        font_size -= 0.5


def build_pdf(grids, size: int, output: Path, playlist_names: list[str]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    font, font_bold, unicode_ok = register_fonts()
    free_label = FREE_LABEL if unicode_ok else FREE_LABEL_ASCII

    page_w, page_h = A4
    margin = 15 * mm
    doc = SimpleDocTemplate(str(output), pagesize=A4,
                            leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=margin,
                            title="Bingo musical", author="bingo_musical.py")

    # Grille carrée : on prend la plus petite dimension disponible
    # (en réservant ~45 mm de hauteur pour le titre et le pied de page).
    avail_w = page_w - 2 * margin
    avail_h = page_h - 2 * margin - 45 * mm
    cell = min(avail_w, avail_h) / size
    padding = max(2.0, cell * 0.06)
    inner = cell - 2 * padding - 1  # surface utile pour le texte

    # Taille de police de départ proportionnelle à la cellule ;
    # fit_paragraph la réduit au besoin cellule par cellule.
    base_font = max(6.0, min(14.0, cell / 6.5))

    title_style = ParagraphStyle("title", fontName=font_bold, fontSize=22,
                                 leading=26, alignment=TA_CENTER, spaceAfter=4)
    subtitle_style = ParagraphStyle("subtitle", fontName=font, fontSize=11,
                                    leading=14, alignment=TA_CENTER,
                                    textColor=colors.HexColor("#555555"))
    cell_style = ParagraphStyle("cell", fontName=font, alignment=TA_CENTER,
                                textColor=colors.HexColor("#1a1a1a"))
    free_style = ParagraphStyle("free", fontName=font_bold, alignment=TA_CENTER,
                                textColor=colors.white)
    footer_style = ParagraphStyle("footer", fontName=font, fontSize=9,
                                  alignment=TA_CENTER,
                                  textColor=colors.HexColor("#777777"))

    header_color = colors.HexColor("#2b2d42")
    story = []
    center = size // 2 if size % 2 == 1 else None

    for index, grid in enumerate(grids, start=1):
        story.append(Paragraph(f"BINGO MUSICAL — Grille n°{index}", title_style))
        story.append(Paragraph(escape(" + ".join(playlist_names)), subtitle_style))
        story.append(Spacer(1, 8 * mm))

        data = []
        for row in grid:
            line = []
            for value in row:
                if value is None:
                    line.append(fit_paragraph(free_label, free_style,
                                              inner, inner, base_font * 1.3))
                else:
                    # Artiste en gras, titre en dessous : plus lisible pendant le jeu.
                    artist, _, title = value.partition(" - ")
                    text = (f"<b>{escape(artist)}</b><br/>{escape(title)}"
                            if title else escape(artist))
                    if font_bold != font:
                        text = text.replace("<b>", f'<font name="{font_bold}">') \
                                   .replace("</b>", "</font>")
                    line.append(fit_paragraph(text, cell_style, inner, inner, base_font))
            data.append(line)

        table = Table(data, colWidths=[cell] * size, rowHeights=[cell] * size)
        style_cmds = [
            ("GRID", (0, 0), (-1, -1), 1.2, header_color),
            ("BOX", (0, 0), (-1, -1), 2.5, header_color),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), padding),
            ("TOPPADDING", (0, 0), (-1, -1), padding),
            ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
            # Damier très léger pour guider l'œil.
            ("ROWBACKGROUNDS", (0, 0), (-1, -1),
             [colors.white, colors.HexColor("#f4f4f8")]),
        ]
        if center is not None:
            style_cmds.append(("BACKGROUND", (center, center), (center, center),
                               colors.HexColor("#ef233c")))
        table.setStyle(TableStyle(style_cmds))
        story.append(table)

        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(
            "Cochez chaque morceau entendu. Une ligne, une colonne ou une diagonale "
            "complète ? Criez « BINGO ! »", footer_style))
        if index < len(grids):
            story.append(PageBreak())

    doc.build(story)


# --------------------------------------------------------------------------- #
# 4. Conducteur animateur
# --------------------------------------------------------------------------- #

def write_conductor(tracks: list[str], output: Path, playlist_names: list[str],
                    rng: random.Random) -> None:
    order = tracks[:]
    rng.shuffle(order)
    width = len(str(len(order)))
    lines = [
        "=" * 60,
        "  BINGO MUSICAL — CONDUCTEUR ANIMATEUR",
        *(f"  Playlist : {name}" for name in playlist_names),
        f"  {len(order)} morceaux — généré le {datetime.now():%d/%m/%Y à %H:%M}",
        "=" * 60,
        "",
        "Jouez les morceaux dans cet ordre et cochez au fur et à mesure.",
        "",
    ]
    lines += [f"[ ] {i:>{width}}. {t}" for i, t in enumerate(order, start=1)]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rng = random.Random(args.seed)  # seed=None => aléatoire « vrai »

    print("🎵 Récupération des playlists Spotify…")
    playlist_names, tracks = fetch_playlists_tracks(args)
    print(f"   Total : {len(tracks)} morceau(x) distinct(s).")

    check_feasibility(len(tracks), args.size, args.cards)

    print(f"🎲 Génération de {args.cards} grille(s) {args.size}x{args.size}…")
    grids = generate_cards(tracks, args.size, args.cards, rng)

    pdf_path = Path(args.output)
    try:
        build_pdf(grids, args.size, pdf_path, playlist_names)
    except ImportError:
        fail("la bibliothèque 'reportlab' est absente. Lancez : pip install reportlab")
    except OSError as exc:
        fail(f"impossible d'écrire le PDF {pdf_path} : {exc}")
    print(f"📄 PDF : {pdf_path.resolve()}")

    conductor_path = Path(args.conductor)
    try:
        write_conductor(tracks, conductor_path, playlist_names, rng)
    except OSError as exc:
        fail(f"impossible d'écrire le conducteur {conductor_path} : {exc}")
    print(f"📝 Conducteur : {conductor_path.resolve()}")
    print("✅ Terminé, bonne soirée !")
    return 0


if __name__ == "__main__":
    sys.exit(main())
