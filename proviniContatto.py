#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow", "reportlab", "rawpy"]
# ///
"""
Provini a contatto A4 (PDF) con il nome del file sotto ogni immagine.

Formati: JPG, PNG, TIFF, RAW Canon (CR2/CR3), Fuji (RAF) e altri RAW (NEF, ARW, DNG...).

Installazione (una volta sola):
    pip install pillow reportlab rawpy

Esempi:
    python provini.py /percorso/foto
    python provini.py /percorso/foto --colonne 6 --righe 6
    python provini.py /percorso/foto --per-cartella
    python provini.py /percorso/foto --uscita /percorso/provini
"""
import argparse
import io
import sys
from pathlib import Path

from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

try:
    import rawpy
except ImportError:
    rawpy = None

Image.MAX_IMAGE_PIXELS = None

EST_NORMALI = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
EST_RAW = {".cr2", ".cr3", ".raf", ".nef", ".arw", ".dng", ".orf", ".rw2"}
LATO_MINIATURA = 600  # pixel del lato lungo nel PDF (buon compromesso peso/qualita)


def apri_miniatura(percorso: Path):
    """Restituisce un'immagine PIL ridotta, oppure None se illeggibile."""
    est = percorso.suffix.lower()
    try:
        if est in EST_RAW:
            if rawpy is None:
                print(f"  [saltato, manca rawpy] {percorso.name}")
                return None
            with rawpy.imread(str(percorso)) as raw:
                da_thumb = False
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        img = Image.open(io.BytesIO(thumb.data))
                    else:
                        img = Image.fromarray(thumb.data)
                    da_thumb = True
                except Exception:
                    # nessuna anteprima incorporata: sviluppo rapido a meta' risoluzione
                    # (rawpy applica gia' la rotazione corretta)
                    rgb = raw.postprocess(half_size=True, use_camera_wb=True)
                    img = Image.fromarray(rgb)
                if da_thumb:
                    # l'anteprima incorporata spesso non e' ruotata: la raddrizzo
                    # in base all'orientamento dichiarato dalla fotocamera
                    img = ImageOps.exif_transpose(img)
                    flip = raw.sizes.flip
                    sensore_verticale = raw.sizes.raw_height > raw.sizes.raw_width
                    finale_verticale = sensore_verticale != (flip in (5, 6))
                    ora_verticale = img.height > img.width
                    if img.width != img.height and ora_verticale != finale_verticale:
                        if flip == 5:
                            img = img.transpose(Image.ROTATE_90)
                        elif flip == 6:
                            img = img.transpose(Image.ROTATE_270)
        else:
            img = Image.open(percorso)
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((LATO_MINIATURA, LATO_MINIATURA))
        return img
    except Exception as e:
        print(f"  [illeggibile] {percorso.name}: {e}")
        return None


def tronca(c, testo, font, size, larghezza_max):
    """Accorcia il nome al centro se non entra nella cella."""
    if c.stringWidth(testo, font, size) <= larghezza_max:
        return testo
    while len(testo) > 6 and c.stringWidth(testo + "…", font, size) > larghezza_max:
        meta = len(testo) // 2
        testo = testo[: meta - 1] + testo[meta:]
    n = len(testo) // 2
    return testo[: n - 1] + "~" + testo[n:]


def crea_pdf(file_lista, uscita: Path, titolo: str, colonne: int, righe: int,
             gutter: float = 2, coricate: bool = True, orario: bool = False):
    larg, alt = A4
    margine = 28
    intestazione = 22
    altezza_nome = 14

    area_w = larg - 2 * margine
    area_h = alt - 2 * margine - intestazione
    cella_w = (area_w - gutter * (colonne - 1)) / colonne
    cella_h = (area_h - gutter * (righe - 1)) / righe
    img_h_max = cella_h - altezza_nome
    per_pagina = colonne * righe
    n_pagine = (len(file_lista) + per_pagina - 1) // per_pagina

    c = canvas.Canvas(str(uscita), pagesize=A4)
    c.setTitle(titolo)
    font, size = "Helvetica", 6.5

    for p in range(n_pagine):
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margine, alt - margine - 8, titolo)
        c.setFont("Helvetica", 8)
        c.drawRightString(larg - margine, alt - margine - 8, f"{p + 1} / {n_pagine}")

        blocco = file_lista[p * per_pagina : (p + 1) * per_pagina]
        for i, f in enumerate(blocco):
            riga, col = divmod(i, colonne)
            x0 = margine + col * (cella_w + gutter)
            y_top = alt - margine - intestazione - riga * (cella_h + gutter)

            img = apri_miniatura(f)
            if img is not None and coricate and img.height > img.width:
                # verticali coricate: tutte le foto risultano in orizzontale
                img = img.transpose(Image.ROTATE_270 if orario else Image.ROTATE_90)
            if img is not None:
                iw, ih = img.size
                scala = min(cella_w / iw, img_h_max / ih)
                w, h = iw * scala, ih * scala
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=82)
                buf.seek(0)
                c.drawImage(ImageReader(buf), x0 + (cella_w - w) / 2,
                            y_top - h, w, h)
            else:
                c.setStrokeGray(0.6)
                c.rect(x0, y_top - img_h_max, cella_w, img_h_max)
                c.setFont(font, size)
                c.drawCentredString(x0 + cella_w / 2, y_top - img_h_max / 2, "illeggibile")

            c.setFont(font, size)
            nome = tronca(c, f.name, font, size, cella_w)
            c.drawCentredString(x0 + cella_w / 2, y_top - img_h_max - 10, nome)
        c.showPage()
    c.save()


def _font(size_px):
    from PIL import ImageFont
    for nome in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(nome, size_px)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size_px)
    except TypeError:
        return ImageFont.load_default()


def crea_jpg(file_lista, cartella_out: Path, prefisso: str, titolo: str, colonne: int,
             righe: int, gutter: float = 2, coricate: bool = True, orario: bool = False,
             dpi: int = 300, qualita: int = 92):
    """Una JPG A4 per pagina (2480x3508 px a 300 dpi): prefisso_001.jpg, prefisso_002.jpg..."""
    from PIL import ImageDraw
    k = dpi / 72.0
    larg, alt = (int(round(v * k)) for v in A4)
    margine, intestazione, altezza_nome = 28 * k, 22 * k, 14 * k
    g = gutter * k
    cella_w = (larg - 2 * margine - g * (colonne - 1)) / colonne
    cella_h = (alt - 2 * margine - intestazione - g * (righe - 1)) / righe
    img_h_max = cella_h - altezza_nome
    per_pagina = colonne * righe
    n_pagine = (len(file_lista) + per_pagina - 1) // per_pagina
    f_nome, f_tit = _font(int(6.5 * k)), _font(int(9 * k))
    creati = []

    for p in range(n_pagine):
        pagina = Image.new("RGB", (larg, alt), "white")
        d = ImageDraw.Draw(pagina)
        d.text((margine, margine), titolo, fill="black", font=f_tit)
        num = f"{p + 1} / {n_pagine}"
        d.text((larg - margine - d.textlength(num, font=f_tit), margine), num,
               fill="black", font=f_tit)

        for i, f in enumerate(file_lista[p * per_pagina:(p + 1) * per_pagina]):
            riga, col = divmod(i, colonne)
            x0 = margine + col * (cella_w + g)
            y_top = margine + intestazione + riga * (cella_h + g)

            img = apri_miniatura(f)
            if img is not None and coricate and img.height > img.width:
                img = img.transpose(Image.ROTATE_270 if orario else Image.ROTATE_90)
            if img is not None:
                iw, ih = img.size
                scala = min(cella_w / iw, img_h_max / ih)
                w, h = max(1, int(iw * scala)), max(1, int(ih * scala))
                img = img.resize((w, h), Image.LANCZOS)
                pagina.paste(img, (int(x0 + (cella_w - w) / 2), int(y_top)))
            else:
                d.rectangle([x0, y_top, x0 + cella_w, y_top + img_h_max], outline="gray")

            nome = f.name
            while len(nome) > 6 and d.textlength(nome, font=f_nome) > cella_w:
                m = len(nome) // 2
                nome = nome[: m - 1] + nome[m:]
            if nome != f.name:
                m = len(nome) // 2
                nome = nome[: m - 1] + "~" + nome[m:]
            tw = d.textlength(nome, font=f_nome)
            d.text((x0 + (cella_w - tw) / 2, y_top + img_h_max + 2 * k), nome,
                   fill="black", font=f_nome)

        out = cartella_out / f"{prefisso}_{p + 1:03d}.jpg"
        pagina.save(out, "JPEG", quality=qualita, dpi=(dpi, dpi))
        creati.append(out)
    return creati


def raccogli(cartella: Path):
    est = EST_NORMALI | EST_RAW
    return sorted(
        (f for f in cartella.rglob("*")
         if f.is_file() and f.suffix.lower() in est and not f.name.startswith("._")),
        key=lambda f: (str(f.parent).lower(), f.name.lower()),
    )


def main():
    ap = argparse.ArgumentParser(description="Provini a contatto A4 in PDF")
    ap.add_argument("cartella", type=Path)
    ap.add_argument("--colonne", type=int, default=5)
    ap.add_argument("--righe", type=int, default=6)
    ap.add_argument("--spazio", type=float, default=2,
                    help="spazio tra i provini in punti (default 2, prima era 8)")
    ap.add_argument("--dritte", action="store_true",
                    help="lascia le verticali in piedi invece di coricarle")
    ap.add_argument("--orario", action="store_true",
                    help="corica le verticali in senso orario (default: antiorario)")
    ap.add_argument("--formato", choices=["pdf", "jpg"], default="pdf",
                    help="pdf (default) oppure jpg: una JPG A4 a 300 dpi per pagina")
    ap.add_argument("--uscita", type=Path, default=None, help="cartella di destinazione dei PDF")
    ap.add_argument("--per-cartella", action="store_true",
                    help="un PDF per ogni sottocartella invece di uno unico")
    a = ap.parse_args()

    if not a.cartella.is_dir():
        sys.exit(f"Cartella non trovata: {a.cartella}")
    uscita = a.uscita or a.cartella
    uscita.mkdir(parents=True, exist_ok=True)

    tutti = raccogli(a.cartella)
    if not tutti:
        sys.exit("Nessuna immagine trovata.")
    print(f"{len(tutti)} immagini trovate.")

    def produci(lista, base, titolo):
        if a.formato == "jpg":
            fatti = crea_jpg(lista, uscita, base, titolo, a.colonne, a.righe,
                             a.spazio, not a.dritte, a.orario)
            print(f"{base}: {len(lista)} immagini, {len(fatti)} JPG")
        else:
            crea_pdf(lista, uscita / f"{base}.pdf", titolo, a.colonne, a.righe,
                     a.spazio, not a.dritte, a.orario)
            print(f"Creato: {uscita / (base + '.pdf')} ({len(lista)} immagini)")

    if a.per_cartella:
        gruppi = {}
        for f in tutti:
            gruppi.setdefault(f.parent, []).append(f)
        for cart, lista in gruppi.items():
            rel = cart.relative_to(a.cartella)
            etichetta = str(rel) if str(rel) != "." else a.cartella.name
            base = "provini_" + etichetta.replace("/", "_").replace("\\", "_")
            produci(lista, base, etichetta)
    else:
        produci(tutti, "provini", a.cartella.name)


if __name__ == "__main__":
    main()
