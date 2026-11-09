#!/usr/bin/env python3
"""
Générateur de grilles de BINGO MUSICAL à partir d'une playlist Spotify.

Produit :
  1. un PDF multipage prêt à imprimer (une grille unique par page) ;
  2. un conducteur .txt pour l'animateur (tous les morceaux, ordre mélangé).

Exemple :
    python bingo_musical.py \
        --playlist "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M" \
        --cards 30 --size 5 \
        --client_id "VOTRE_CLIENT_ID" --client_secret "VOTRE_CLIENT_SECRET"

Dépendances : pip install spotipy reportlab
"""

from __future__ import annotations

import argparse
import math
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #

FREE_LABEL = "★\u00a0FREE\u00a0★"  # espaces insécables : une seule ligne
FREE_LABEL_ASCII = "*\u00a0FREE\u00a0*"  # repli si aucune police ne contient « ★ »
MIN_SIZE, MAX_SIZE = 2, 10
MAX_UNIQUE_ATTEMPTS = 1000  # tirages max pour obtenir une grille inédite

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
    parser.add_argument("--playlist", required=True,
                        help="URL (ou URI / ID) de la playlist Spotify.")
    parser.add_argument("--cards", required=True, type=int,
                        help="Nombre de grilles uniques à générer.")
    parser.add_argument("--size", type=int, default=5,
                        help="Taille de la grille (N pour N x N). Défaut : 5.")
    parser.add_argument("--client_id", required=True, help="Client ID Spotify.")
    parser.add_argument("--client_secret", required=True, help="Client Secret Spotify.")
    # Options supplémentaires (facultatives)
    parser.add_argument("--output", default="bingo_grilles.pdf",
                        help="Fichier PDF de sortie. Défaut : bingo_grilles.pdf")
    parser.add_argument("--conductor", default="conducteur_animateur.txt",
                        help="Fichier texte du conducteur. Défaut : conducteur_animateur.txt")
    parser.add_argument("--seed", type=int, default=None,
                        help="Graine aléatoire (pour reproduire exactement un tirage).")
    args = parser.parse_args(argv)

    if args.cards < 1:
        parser.error("--cards doit être un entier strictement positif.")
    if not MIN_SIZE <= args.size <= MAX_SIZE:
        parser.error(f"--size doit être compris entre {MIN_SIZE} et {MAX_SIZE}.")
    return args


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


def fetch_playlist_tracks(playlist_url: str, client_id: str,
                          client_secret: str) -> tuple[str, list[str]]:
    """Renvoie (nom de la playlist, liste « Artiste - Titre » sans doublons)."""
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
    except ImportError:
        fail("la bibliothèque 'spotipy' est absente. Lancez : pip install spotipy")

    playlist_id = extract_playlist_id(playlist_url)
    sp = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(client_id=client_id,
                                              client_secret=client_secret),
        requests_timeout=15,
        retries=3,
    )

    try:
        playlist_name = sp.playlist(playlist_id, fields="name")["name"]
        # La pagination est gérée par sp.next() (100 morceaux par page).
        page = sp.playlist_items(
            playlist_id,
            additional_types=("track",),
            limit=100,
        )
        tracks: list[str] = []
        seen: set[str] = set()
        while page:
            for item in page.get("items", []):
                # « track » (historique) ou « item » (nommage récent de l'API).
                track = item.get("track") or item.get("item")
                # On ignore les entrées vides, locales ou les épisodes de podcast.
                if not track or track.get("type") != "track" or not track.get("name"):
                    continue
                artists = ", ".join(a["name"] for a in track.get("artists", []) if a.get("name"))
                label = f"{artists} - {track['name']}" if artists else track["name"]
                key = label.casefold()
                if key not in seen:  # dédoublonnage (même morceau ajouté deux fois)
                    seen.add(key)
                    tracks.append(label)
            page = sp.next(page) if page.get("next") else None
    except spotipy.oauth2.SpotifyOauthError as exc:
        fail(f"authentification Spotify refusée (Client ID / Secret ?) : {exc}")
    except spotipy.SpotifyException as exc:
        hint = ""
        if exc.http_status == 404:
            hint = (" — playlist introuvable, privée, ou générée par Spotify "
                    "(ces dernières ne sont plus accessibles aux nouvelles applications).")
        fail(f"l'API Spotify a répondu {exc.http_status} : {exc.msg}{hint}")
    except Exception as exc:  # réseau, timeout…
        fail(f"impossible de joindre Spotify : {exc}")

    return playlist_name, tracks


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


def build_pdf(grids, size: int, output: Path, playlist_name: str) -> None:
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
        story.append(Paragraph(escape(playlist_name), subtitle_style))
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

def write_conductor(tracks: list[str], output: Path, playlist_name: str,
                    rng: random.Random) -> None:
    order = tracks[:]
    rng.shuffle(order)
    width = len(str(len(order)))
    lines = [
        "=" * 60,
        "  BINGO MUSICAL — CONDUCTEUR ANIMATEUR",
        f"  Playlist : {playlist_name}",
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

    print("🎵 Récupération de la playlist Spotify…")
    playlist_name, tracks = fetch_playlist_tracks(args.playlist, args.client_id,
                                                  args.client_secret)
    print(f"   « {playlist_name} » : {len(tracks)} morceau(x) distinct(s).")

    check_feasibility(len(tracks), args.size, args.cards)

    print(f"🎲 Génération de {args.cards} grille(s) {args.size}x{args.size}…")
    grids = generate_cards(tracks, args.size, args.cards, rng)

    pdf_path = Path(args.output)
    try:
        build_pdf(grids, args.size, pdf_path, playlist_name)
    except ImportError:
        fail("la bibliothèque 'reportlab' est absente. Lancez : pip install reportlab")
    except OSError as exc:
        fail(f"impossible d'écrire le PDF {pdf_path} : {exc}")
    print(f"📄 PDF : {pdf_path.resolve()}")

    conductor_path = Path(args.conductor)
    try:
        write_conductor(tracks, conductor_path, playlist_name, rng)
    except OSError as exc:
        fail(f"impossible d'écrire le conducteur {conductor_path} : {exc}")
    print(f"📝 Conducteur : {conductor_path.resolve()}")
    print("✅ Terminé, bonne soirée !")
    return 0


if __name__ == "__main__":
    sys.exit(main())
