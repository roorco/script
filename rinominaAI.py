#!/usr/bin/env python3
"""
Rinomina file Adobe Illustrator (.ai) scegliendo interattivamente,
file per file, tra più candidati: titolo nei metadati, prima frase
di testo nel documento, data di creazione/modifica, o un nome scritto
a mano.

Richiede:
    pip install pypdf pdfplumber --break-system-packages

Uso:
    python rinomina_ai.py /percorso/cartella
"""

import multiprocessing as mp
import re
import subprocess
import sys
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

PAROLA_VALIDA = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
FINE_FRASE = re.compile(r"[.!?…]$")
CARATTERI_VIETATI = re.compile(r'[\\/:*?"<>|\n\r\t]')


def pulisci_per_filename(testo: str, max_caratteri: int = 80) -> str:
    testo = CARATTERI_VIETATI.sub("", testo)
    testo = re.sub(r"\s+", " ", testo).strip()
    testo = testo.rstrip(" .")
    if len(testo) > max_caratteri:
        testo = testo[:max_caratteri].rsplit(" ", 1)[0].strip()
    return testo.replace(" ", "_")


def prima_frase_da_parole(parole, max_parole=12, max_caratteri=80):
    if not parole:
        return None
    frase = []
    for p in parole:
        p = p.strip()
        if not p:
            continue
        if not frase and not PAROLA_VALIDA.search(p):
            continue
        frase.append(p)
        if FINE_FRASE.search(p) and len(frase) >= 2:
            break
        if len(frase) >= max_parole:
            break
        if len(" ".join(frase)) >= max_caratteri:
            break
    if not frase:
        return None
    return pulisci_per_filename(" ".join(frase), max_caratteri)


def ottieni_titolo_metadata(ai_path: Path):
    try:
        reader = PdfReader(str(ai_path), strict=False)
        titolo = reader.metadata.title if reader.metadata else None
    except Exception:
        return None
    if not titolo or not titolo.strip():
        return None
    titolo = titolo.strip().replace("\\", "/").rsplit("/", 1)[-1]
    if not re.search(r"[^\W\d_]", titolo, re.UNICODE):
        return None
    return pulisci_per_filename(titolo)


def prima_frase_testo(ai_path: Path):
    try:
        with pdfplumber.open(str(ai_path)) as pdf:
            if not pdf.pages:
                return None
            testo = pdf.pages[0].extract_text() or ""
    except Exception:
        return None
    if not testo.strip():
        return None
    return prima_frase_da_parole(testo.split())


def _worker_estrai_candidati(ai_path_str, coda):
    """Eseguito in un processo separato, così un'estrazione bloccata
    su un file pesante può essere interrotta forzatamente dal processo
    principale dopo il timeout."""
    try:
        ai_path = Path(ai_path_str)
        candidati = {}

        titolo = ottieni_titolo_metadata(ai_path)
        if titolo:
            candidati["m"] = ("Titolo nei metadati", titolo)

        frase = prima_frase_testo(ai_path)
        if frase:
            candidati["t"] = ("Prima frase nel testo", frase)

        coda.put(candidati)
    except Exception:
        coda.put({})


def estrai_candidati_con_timeout(ai_path: Path, timeout: float = 20):
    """Restituisce (candidati, scaduto). Se il processo non termina entro
    'timeout' secondi viene interrotto forzatamente."""
    coda = mp.Queue()
    processo = mp.Process(target=_worker_estrai_candidati, args=(str(ai_path), coda))
    processo.start()
    processo.join(timeout)

    if processo.is_alive():
        processo.terminate()
        processo.join()
        return {}, True

    try:
        candidati = coda.get_nowait()
    except Exception:
        candidati = {}
    return candidati, False


def data_file(ai_path: Path):
    try:
        risultato = subprocess.run(
            ["exiftool", "-s3", "-CreateDate", "-FileModifyDate", str(ai_path)],
            capture_output=True, text=True, timeout=10,
        )
        righe = [r.strip() for r in risultato.stdout.splitlines() if r.strip()]
        data_raw = righe[0] if righe else None
    except Exception:
        data_raw = None

    if not data_raw:
        return None

    m = re.match(r"(\d{4})[:\-](\d{2})[:\-](\d{2})", data_raw)
    if not m:
        return None
    aa, mm, gg = m.group(1)[2:], m.group(2), m.group(3)
    return f"{aa}{mm}{gg}"


def nome_file_sicuro(nome: str, estensione: str, cartella: Path) -> Path:
    base = cartella / f"{nome}{estensione}"
    if not base.exists():
        return base
    contatore = 2
    while True:
        candidato = cartella / f"{nome}_{contatore}{estensione}"
        if not candidato.exists():
            return candidato
        contatore += 1


def main():
    if len(sys.argv) < 2:
        print("Uso: python rinomina_ai.py /percorso/cartella")
        sys.exit(1)

    cartella = Path(sys.argv[1]).expanduser().resolve()
    if not cartella.is_dir():
        print(f"Errore: '{cartella}' non è una cartella valida.")
        sys.exit(1)

    file_ai = sorted(cartella.glob("*.ai"))
    if not file_ai:
        print("Nessun file .ai trovato nella cartella.")
        return

    print(f"Trovati {len(file_ai)} file .ai\n")

    for ai_path in file_ai:
        print(f"\n{'='*60}")
        print(f"File: {ai_path.name}")

        candidati, scaduto = estrai_candidati_con_timeout(ai_path, timeout=20)
        if scaduto:
            print("  [Estrazione testo/titolo troppo lenta, timeout dopo 20s — salto questa parte]")

        data = data_file(ai_path)
        if data:
            candidati["d"] = ("Data (AAMMGG)", data)

        if not candidati:
            print("  Nessun candidato automatico trovato (nessun testo estraibile, "
                  "probabile file senza compatibilità PDF, e nessuna data leggibile).")

        for chiave, (etichetta, valore) in candidati.items():
            print(f"  [{chiave}] {etichetta}: {valore}")
        print("  [s] Scrivi un nome a mano")
        print("  [invio] Salta questo file")

        scelta = input("Scegli un'opzione: ").strip().lower()

        if scelta == "":
            print("  Saltato.")
            continue
        elif scelta == "s":
            nuovo_nome = input("  Nuovo nome (senza estensione): ").strip()
            nuovo_nome = pulisci_per_filename(nuovo_nome)
            if not nuovo_nome:
                print("  Nome vuoto, saltato.")
                continue
        elif scelta in candidati:
            nuovo_nome = candidati[scelta][1]
        else:
            print("  Opzione non valida, saltato.")
            continue

        nuovo_path = nome_file_sicuro(nuovo_nome, ai_path.suffix, cartella)
        conferma = input(f"  Rinomino in '{nuovo_path.name}'? [S/n]: ").strip().lower()
        if conferma in ("", "s", "si", "sì", "y", "yes"):
            ai_path.rename(nuovo_path)
            print(f"  -> Rinominato in {nuovo_path.name}")
        else:
            print("  Annullato.")


if __name__ == "__main__":
    main()
