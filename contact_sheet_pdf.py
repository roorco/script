#!/usr/bin/env python3
"""
Crea un "foglio di contatto": un'unica immagine con la prima pagina di
ogni PDF di una cartella, in miniatura, etichettata con il nome del file.
Utile per farsi un'idea veloce del contenuto di tanti PDF insieme, senza
doverli aprire uno per uno.

Uso:
    python contact_sheet_pdf.py /percorso/cartella
    python contact_sheet_pdf.py /percorso/cartella --output anteprima.jpg
    python contact_sheet_pdf.py /percorso/cartella --colonne 5 --dpi 100
    python contact_sheet_pdf.py /percorso/cartella --larghezza 300

Richiede:
    - poppler-utils (comando pdftoppm) - di solito già presente su Linux/Mac
    - ImageMagick (comando montage) - su Debian/Ubuntu: sudo apt install imagemagick
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def rasterizza_prima_pagina(pdf_path: Path, cartella_tmp: Path, dpi: int) -> Path | None:
    """Rasterizza la prima pagina di un PDF in JPEG, restituendo il percorso
    dell'immagine creata (o None se fallisce, es. PDF corrotto/protetto)."""
    prefisso = cartella_tmp / pdf_path.stem
    try:
        subprocess.run(
            ["pdftoppm", "-jpeg", "-r", str(dpi), "-f", "1", "-l", "1", str(pdf_path), str(prefisso)],
            capture_output=True,
            timeout=30,
        )
    except Exception:
        return None

    candidati = sorted(cartella_tmp.glob(f"{pdf_path.stem}*.jpg"))
    return candidati[0] if candidati else None


def main():
    parser = argparse.ArgumentParser(description="Crea un foglio di contatto con la prima pagina di tanti PDF")
    parser.add_argument("cartella", type=str, help="Cartella contenente i PDF")
    parser.add_argument("--output", type=str, default="foglio_contatto.jpg", help="Nome del file immagine risultante (default foglio_contatto.jpg)")
    parser.add_argument("--colonne", type=int, default=4, help="Numero di colonne della griglia (default 4)")
    parser.add_argument("--larghezza", type=int, default=250, help="Larghezza in pixel di ogni miniatura (default 250)")
    parser.add_argument("--dpi", type=int, default=80, help="Risoluzione di rasterizzazione, più bassa = più veloce (default 80)")
    args = parser.parse_args()

    for comando in ("pdftoppm", "montage"):
        if not shutil.which(comando):
            print(f"Errore: comando '{comando}' non trovato. Installa poppler-utils e imagemagick.")
            sys.exit(1)

    cartella = Path(args.cartella).expanduser().resolve()
    if not cartella.is_dir():
        print(f"Errore: '{cartella}' non è una cartella valida.")
        sys.exit(1)

    pdf_files = sorted(cartella.glob("*.pdf"))
    if not pdf_files:
        print("Nessun PDF trovato nella cartella.")
        return

    print(f"Trovati {len(pdf_files)} PDF. Rasterizzo la prima pagina di ciascuno...")

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        cartella_tmp = Path(tmp_dir_str)
        immagini = []
        falliti = []

        for pdf_path in pdf_files:
            print(f"  {pdf_path.name} ...", end="", flush=True)
            immagine = rasterizza_prima_pagina(pdf_path, cartella_tmp, args.dpi)
            if immagine:
                immagini.append((pdf_path.name, immagine))
                print(" ok")
            else:
                falliti.append(pdf_path.name)
                print(" FALLITO")

        if not immagini:
            print("Nessuna pagina è stata rasterizzata con successo.")
            return

        output_path = Path(args.output).expanduser().resolve()

        comando_montage = ["montage"]
        for nome_originale, immagine in immagini:
            comando_montage += ["-label", nome_originale, str(immagine)]
        comando_montage += [
            "-tile", f"{args.colonne}x",
            "-geometry", f"{args.larghezza}x{args.larghezza}+5+5>",
            "-background", "white",
            str(output_path),
        ]

        print("\nComponendo il foglio di contatto...")
        risultato = subprocess.run(comando_montage, capture_output=True, text=True)

        if risultato.returncode != 0:
            print("Errore da 'montage':", risultato.stderr)
            sys.exit(1)

        print(f"\nFatto: {output_path}")
        if falliti:
            print(f"\n{len(falliti)} file non rasterizzati (probabilmente protetti da password o corrotti):")
            for nome in falliti:
                print(f"  - {nome}")


if __name__ == "__main__":
    main()
