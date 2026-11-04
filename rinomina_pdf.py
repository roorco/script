#!/usr/bin/env python3
"""
Rinomina i file PDF di una cartella usando la prima FRASE "vera"
trovata nel testo della prima pagina (nell'ordine visivo, non nel
solo ordine interno del file PDF).

Uso:
    python rinomina_pdf.py /percorso/cartella
    python rinomina_pdf.py /percorso/cartella --dry-run     # solo anteprima, non rinomina
    python rinomina_pdf.py /percorso/cartella --pages 2     # controlla le prime 2 pagine se la 1 è vuota
    python rinomina_pdf.py /percorso/cartella --max-parole 10   # più o meno lunga la frase-titolo
    python rinomina_pdf.py /percorso/cartella --max-caratteri 100

Richiede:
    pip install pypdf pdfplumber fonttools --break-system-packages

Opzionale, per l'OCR sui PDF scansionati (attivo di default se disponibile):
    pip install pytesseract pillow --break-system-packages
    + il programma di sistema 'tesseract-ocr' (con i pacchetti lingua che
      servono, es. tesseract-ocr-ita, tesseract-ocr-fra)
    Disattivabile con --no-ocr.
"""

import argparse
import logging
import multiprocessing as mp
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

try:
    import pytesseract
    from PIL import Image
    OCR_DISPONIBILE = True
except ImportError:
    OCR_DISPONIBILE = False

# pypdf e pdfminer (usato internamente da pdfplumber) stampano avvisi molto
# verbosi quando incontrano PDF con struttura interna malformata (xref
# rotto, stream senza lunghezza dichiarata, ecc.). Non sono errori
# bloccanti: lo script ha già i fallback per questi casi. Li silenziamo
# per non intasare l'output.
logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("pdfminer").setLevel(logging.ERROR)

# Una "parola vera" ha almeno 2 caratteri alfabetici (scarta numeri di
# pagina, sigle isolate, simboli sparsi, ecc.)
PAROLA_VALIDA = re.compile(r"[^\W\d_]{2,}", re.UNICODE)

# Punteggiatura che segnala la fine di una frase
FINE_FRASE = re.compile(r"[.!?…]$")

# Caratteri non ammessi nei nomi file (Windows/Mac/Linux)
CARATTERI_VIETATI = re.compile(r'[\\/:*?"<>|\n\r\t]')


# Compressione lettere ripetute: alcuni PDF simulano il grassetto disegnando
# ogni lettera più volte con un lieve spostamento (es. "CCCCHHHHAAAARRRRTTTTEEEE"
# invece di "CHARTE"). Non collassiamo semplicemente a 1 carattere, perché
# altrimenti si perdono le doppie vere (es. "ENVIRONNEMENT" -> "ENVIRONEMENT").
# Rileviamo invece il fattore di duplicazione dominante (es. 4x, se ogni
# lettera è ripetuta 4 volte) e dividiamo ogni sequenza per quel fattore.
RUN_LETTERA = re.compile(r"([^\W\d_])\1*", re.UNICODE)


def fattore_duplicazione_parola(testo: str) -> int:
    """
    Rileva se QUESTA parola sembra scritta con lettere duplicate per un
    finto grassetto (es. 'CCCCHHHH...' con fattore 4), guardando la
    lunghezza di run più frequente tra i suoi caratteri ripetuti. Richiede
    che quella lunghezza sia condivisa dalla maggioranza dei run della
    parola, per non scambiare doppie legittime (es. 'belle') per grassetto
    duplicato. Restituisce 1 se la parola sembra normale.
    """
    from collections import Counter

    lunghezze = [len(m.group(0)) for m in RUN_LETTERA.finditer(testo)]
    if not lunghezze:
        return 1
    fattore, conteggio = Counter(lunghezze).most_common(1)[0]
    if fattore >= 2 and conteggio >= max(2, len(lunghezze) // 2):
        return fattore
    return 1


def comprimi_lettere_ripetute(testo: str) -> str:
    fattore = fattore_duplicazione_parola(testo)
    if fattore <= 1:
        return testo

    def sostituisci(m):
        run = m.group(0)
        n = max(1, round(len(run) / fattore))
        return m.group(1) * n

    return RUN_LETTERA.sub(sostituisci, testo)


# Prefissi/suffissi tipici che compaiono nel campo Titolo dei metadati
# quando è stato generato automaticamente da Word/InDesign a partire dal
# nome del file originale, e vanno ripuliti.
PREFISSO_TITOLO_SPAZZATURA = re.compile(r"^(Microsoft Word - |Microsoft PowerPoint - )", re.IGNORECASE)
SUFFISSO_ESTENSIONE_SPAZZATURA = re.compile(r"\.(docx?|indd|rtf|odt|pptx?|pub)$", re.IGNORECASE)


def ottieni_titolo_metadata(pdf_path: Path) -> str | None:
    """
    Legge il campo Titolo dai metadati del PDF (lo stesso che mostrano
    lettori come Okular nella barra del titolo). Se presente e non è
    chiaramente un artefatto del nome file originale (es. "Microsoft
    Word - Nome.doc"), lo ripulisce e lo restituisce.
    """
    try:
        reader = PdfReader(str(pdf_path), strict=False)
        titolo = reader.metadata.title if reader.metadata else None
    except Exception:
        return None

    if not titolo or not titolo.strip():
        return None

    titolo = titolo.strip()
    # Se il titolo è in realtà un percorso file completo (es. da Word/InDesign
    # su Windows: "C:\Users\Nome\Desktop\Documento.doc"), teniamo solo
    # l'ultimo segmento, sia con backslash che con slash.
    titolo = titolo.replace("\\", "/").rsplit("/", 1)[-1]
    titolo = PREFISSO_TITOLO_SPAZZATURA.sub("", titolo)
    titolo = SUFFISSO_ESTENSIONE_SPAZZATURA.sub("", titolo)
    titolo = titolo.strip()

    if not re.search(r"[^\W\d_]", titolo, re.UNICODE):
        return None

    return titolo


def pulisci_per_filename(testo: str, max_caratteri: int) -> str:
    """Sanifica una stringa per usarla come nome file."""
    testo = CARATTERI_VIETATI.sub("", testo)
    testo = re.sub(r"\s+", " ", testo).strip()
    testo = testo.rstrip(" .")  # niente spazi/punti finali (problemi su Windows)
    if len(testo) > max_caratteri:
        testo = testo[:max_caratteri].rsplit(" ", 1)[0].strip()
    testo = testo.replace(" ", "_")
    return testo


def costruisci_prima_frase(parole_ordinate, max_parole: int, max_caratteri: int):
    """
    Costruisce la prima frase 'vera' a partire da una lista di parole già
    in ordine di lettura. Ogni elemento di parole_ordinate è una stringa
    (fallback pypdf/pdftotext) oppure un dict {'text','top','bottom'}
    (metodo posizionale con pdfplumber).

    Si ferma:
    - alla prima punteggiatura di fine frase (. ! ? …), oppure
    - a un salto verticale anomalo tra una riga e la successiva (segno
      che si è usciti dal blocco di testo del titolo, es. un blocco
      immagine con testo sovrapposto più sotto nella pagina), oppure
    - dopo max_parole parole o max_caratteri caratteri, come limite di
      sicurezza per i titoli senza punteggiatura.
    """
    if not parole_ordinate:
        return None

    frase_parole = []
    iniziata = False
    last_bottom = None

    for elem in parole_ordinate:
        if isinstance(elem, dict):
            parola, top, bottom = elem["text"], elem["top"], elem["bottom"]
        else:
            parola, top, bottom = elem, None, None

        parola = comprimi_lettere_ripetute(parola)
        if not parola:
            continue

        if not iniziata:
            if not PAROLA_VALIDA.search(parola):
                continue
            iniziata = True
        elif top is not None and last_bottom is not None:
            altezza_riga = max(bottom - top, 1)
            if top - last_bottom > altezza_riga * 1.8:
                break  # salto anomalo: nuovo blocco di testo, ci fermiamo qui

        frase_parole.append(parola)
        if bottom is not None:
            last_bottom = bottom

        testo_corrente = " ".join(frase_parole)
        if len(testo_corrente) >= max_caratteri:
            break
        if FINE_FRASE.search(parola) and len(frase_parole) >= 2:
            break
        if len(frase_parole) >= max_parole:
            break

    if not frase_parole:
        return None

    frase = " ".join(frase_parole)
    frase = pulisci_per_filename(frase, max_caratteri)
    return frase or None


def estrai_parole_posizionali(pdf_path: Path, max_pagine: int):
    """
    Estrae le parole della pagina nell'ordine VISIVO (alto->basso,
    sinistra->destra), non nell'ordine interno del flusso PDF, mantenendo
    le coordinate (top/bottom) per poter rilevare i cambi di blocco.
    """
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i in range(min(max_pagine, len(pdf.pages))):
                page = pdf.pages[i]
                try:
                    parole = page.extract_words(x_tolerance=8, y_tolerance=3)
                except Exception:
                    continue
                if not parole:
                    continue
                parole_ordinate = sorted(parole, key=lambda w: (round(w["top"], 0), w["x0"]))
                risultato = [
                    {"text": w["text"], "top": w["top"], "bottom": w["bottom"]}
                    for w in parole_ordinate
                    if w["text"].strip()
                ]
                if risultato:
                    return risultato
    except Exception:
        return None
    return None


def estrai_con_pdftotext(pdf_path: Path, max_pagine: int):
    """Fallback con pdftotext (poppler-utils), più tollerante ai PDF corrotti."""
    try:
        risultato = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(max_pagine), str(pdf_path), "-"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        testo = risultato.stdout or ""
        parole = testo.split()
        return parole or None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def estrai_con_ocr(pdf_path: Path, max_pagine: int, dpi: int, lingua: str):
    """
    Fallback per PDF scansionati (senza testo estraibile): rasterizza le
    pagine con pdftoppm e ci passa sopra l'OCR di Tesseract. Usa
    image_to_data invece di image_to_string per ottenere anche la
    posizione di ogni parola (top/bottom), così possiamo riusare la
    stessa logica di rilevamento del cambio blocco usata per i PDF con
    testo nativo (utile per non sconfinare da un titolo scansionato al
    paragrafo successivo).
    """
    if not OCR_DISPONIBILE:
        return None

    with tempfile.TemporaryDirectory() as tmp_dir:
        prefisso = str(Path(tmp_dir) / "pagina")
        try:
            subprocess.run(
                ["pdftoppm", "-jpeg", "-r", str(dpi), "-f", "1", "-l", str(max_pagine), str(pdf_path), prefisso],
                capture_output=True,
                timeout=60,
            )
        except FileNotFoundError:
            return None  # pdftoppm (poppler-utils) non installato
        except Exception:
            return None

        immagini = sorted(Path(tmp_dir).glob("pagina*.jpg"))
        if not immagini:
            return None

        for immagine in immagini:
            try:
                dati = pytesseract.image_to_data(
                    Image.open(immagine), lang=lingua, output_type=pytesseract.Output.DICT
                )
            except Exception:
                continue

            risultato = []
            n = len(dati.get("text", []))
            for i in range(n):
                testo = dati["text"][i].strip()
                if not testo:
                    continue
                # Scarta riconoscimenti a bassissima confidenza (spesso rumore
                # su sfondi complessi, es. mappe o fotografie).
                try:
                    confidenza = float(dati["conf"][i])
                except (ValueError, TypeError):
                    confidenza = -1
                if confidenza != -1 and confidenza < 30:
                    continue
                top = float(dati["top"][i])
                bottom = top + float(dati["height"][i])
                risultato.append({"text": testo, "top": top, "bottom": bottom})

            if risultato:
                return risultato

    return None


def estrai_con_pypdf(pdf_path: Path, max_pagine: int):
    """Fallback con pypdf (più permissivo con alcuni PDF malformati)."""
    testo_totale = ""
    errore = None
    try:
        reader = PdfReader(str(pdf_path), strict=False)
        for i in range(min(max_pagine, len(reader.pages))):
            try:
                testo_totale += (reader.pages[i].extract_text() or "") + "\n"
            except Exception:
                pass
    except Exception as e:
        errore = e
    parole = testo_totale.split()
    return (parole or None), errore


def estrai_prima_frase(pdf_path: Path, max_pagine: int, max_parole: int, max_caratteri: int, usa_ocr: bool, ocr_dpi: int, ocr_lingua: str):
    # Metodo 0: titolo nei metadati del PDF (quello mostrato da lettori
    # come Okular), se presente e non un artefatto del nome file originale.
    titolo = ottieni_titolo_metadata(pdf_path)
    if titolo:
        frase = pulisci_per_filename(titolo, max_caratteri)
        if frase:
            return frase

    # Metodo primario: posizione reale sulla pagina (pdfplumber)
    parole = estrai_parole_posizionali(pdf_path, max_pagine)
    frase = costruisci_prima_frase(parole, max_parole, max_caratteri) if parole else None
    if frase:
        return frase

    # Fallback 1: pypdf
    parole, errore_pypdf = estrai_con_pypdf(pdf_path, max_pagine)
    frase = costruisci_prima_frase(parole, max_parole, max_caratteri) if parole else None
    if frase:
        return frase

    # Fallback 2: pdftotext (tollerante ai PDF con xref corrotto)
    parole = estrai_con_pdftotext(pdf_path, max_pagine)
    frase = costruisci_prima_frase(parole, max_parole, max_caratteri) if parole else None
    if frase:
        return frase

    # Fallback 3: OCR, per i PDF scansionati (nessun testo estraibile nei
    # modi precedenti perché la pagina è in realtà solo un'immagine).
    if usa_ocr:
        parole = estrai_con_ocr(pdf_path, max_pagine, ocr_dpi, ocr_lingua)
        frase = costruisci_prima_frase(parole, max_parole, max_caratteri) if parole else None
        if frase:
            return frase

    if errore_pypdf:
        print(f"  [ERRORE apertura, anche fallback falliti] {pdf_path.name}: {errore_pypdf}")

    return None  # nessun testo trovato (probabile PDF scansionato o corrotto)


def _worker_estrai(pdf_path_str: str, max_pagine: int, max_parole: int, max_caratteri: int, usa_ocr: bool, ocr_dpi: int, ocr_lingua: str, coda) -> None:
    """Eseguito in un processo separato: se il PDF è protetto da password
    lo segnala subito, altrimenti tenta l'estrazione normale. Qualsiasi
    eccezione imprevista non deve far sparire il risultato: mettiamo
    sempre qualcosa in coda."""
    try:
        try:
            controllo = PdfReader(pdf_path_str, strict=False)
            if controllo.is_encrypted:
                coda.put("__CIFRATO__")
                return
        except Exception:
            pass  # se anche questo controllo fallisce, proviamo comunque l'estrazione normale

        risultato = estrai_prima_frase(
            Path(pdf_path_str), max_pagine, max_parole, max_caratteri, usa_ocr, ocr_dpi, ocr_lingua
        )
        coda.put(risultato)
    except Exception:
        coda.put(None)


def estrai_con_timeout(pdf_path: Path, max_pagine: int, max_parole: int, max_caratteri: int, timeout: float, usa_ocr: bool, ocr_dpi: int, ocr_lingua: str):
    """
    Esegue l'estrazione in un processo separato con un limite di tempo.
    Restituisce (risultato, scaduto). Se il processo non termina entro
    'timeout' secondi viene interrotto forzatamente, per evitare che un
    singolo file bloccato fermi l'elaborazione dell'intera cartella.
    """
    coda = mp.Queue()
    processo = mp.Process(
        target=_worker_estrai,
        args=(str(pdf_path), max_pagine, max_parole, max_caratteri, usa_ocr, ocr_dpi, ocr_lingua, coda),
    )
    processo.start()
    processo.join(timeout)

    if processo.is_alive():
        processo.terminate()
        processo.join()
        return None, True

    try:
        risultato = coda.get_nowait()
    except Exception:
        risultato = None
    return risultato, False


def nome_file_sicuro(nome: str, estensione: str, cartella: Path) -> Path:
    """Evita di sovrascrivere file esistenti aggiungendo un contatore."""
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
    parser = argparse.ArgumentParser(description="Rinomina PDF con la prima frase del testo")
    parser.add_argument("cartella", type=str, help="Cartella contenente i PDF")
    parser.add_argument("--dry-run", action="store_true", help="Mostra solo l'anteprima, non rinomina")
    parser.add_argument("--pages", type=int, default=1, help="Numero di pagine da controllare se la prima è vuota (default 1)")
    parser.add_argument("--max-parole", type=int, default=12, help="Numero massimo di parole nella frase-titolo se non trova un punto (default 12)")
    parser.add_argument("--max-caratteri", type=int, default=80, help="Lunghezza massima del nome file generato (default 80)")
    parser.add_argument("--timeout", type=float, default=20, help="Secondi massimi per file prima di saltarlo (default 20)")
    parser.add_argument("--no-ocr", action="store_true", help="Disattiva l'OCR per i PDF scansionati (attivo di default se disponibile)")
    parser.add_argument("--ocr-lang", type=str, default="ita+fra+eng", help="Lingue per l'OCR, codici Tesseract separati da '+' (default ita+fra+eng)")
    parser.add_argument("--ocr-dpi", type=int, default=200, help="Risoluzione di rasterizzazione per l'OCR (default 200)")
    args = parser.parse_args()

    cartella = Path(args.cartella).expanduser().resolve()
    if not cartella.is_dir():
        print(f"Errore: '{cartella}' non è una cartella valida.")
        sys.exit(1)

    pdf_files = sorted(cartella.glob("*.pdf"))
    if not pdf_files:
        print("Nessun PDF trovato nella cartella.")
        return

    usa_ocr = OCR_DISPONIBILE and not args.no_ocr
    if not args.no_ocr and not OCR_DISPONIBILE:
        print(
            "Nota: l'OCR non è disponibile (mancano pytesseract/Pillow o il programma "
            "tesseract). Installa con:\n"
            "  pip install pytesseract pillow --break-system-packages\n"
            "  e il pacchetto di sistema 'tesseract-ocr' (+ eventuali lingue, es. "
            "'tesseract-ocr-ita').\n"
            "Proseguo senza OCR per i PDF scansionati.\n"
        )

    print(f"Trovati {len(pdf_files)} PDF in {cartella}\n")

    non_trovati = []
    cifrati = []
    scaduti = []

    for pdf_path in pdf_files:
        print(f"  Elaboro: {pdf_path.name} ...", end="", flush=True)

        frase, scaduto = estrai_con_timeout(
            pdf_path, args.pages, args.max_parole, args.max_caratteri, args.timeout,
            usa_ocr, args.ocr_dpi, args.ocr_lang,
        )

        if scaduto:
            print(f" [TIMEOUT dopo {args.timeout:g}s, saltato]")
            scaduti.append(pdf_path.name)
            continue

        if frase == "__CIFRATO__":
            print(" [SALTATO - PDF protetto da password]")
            cifrati.append(pdf_path.name)
            continue

        if not frase:
            etichetta = (
                " [SALTATO - nessun testo trovato neanche con OCR]"
                if usa_ocr
                else " [SALTATO - nessun testo estratto, forse scansionato]"
            )
            print(etichetta)
            non_trovati.append(pdf_path.name)
            continue

        nuovo_path = nome_file_sicuro(frase, pdf_path.suffix, cartella)

        if args.dry_run:
            print(f" -> {nuovo_path.name}  (anteprima)")
        else:
            pdf_path.rename(nuovo_path)
            print(f" -> {nuovo_path.name}")

    if non_trovati:
        print(f"\n{len(non_trovati)} file non rinominati (nessun testo trovato):")
        for nome in non_trovati:
            print(f"  - {nome}")
        if usa_ocr:
            print("Anche l'OCR non ha trovato testo leggibile in questi file (immagine di scarsa qualità, pagina vuota, o lingua non tra quelle indicate con --ocr-lang).")
        else:
            print("Per questi potrebbe servire l'OCR (probabili PDF scansionati). Installa pytesseract/Pillow/tesseract-ocr e riprova senza --no-ocr.")

    if cifrati:
        print(f"\n{len(cifrati)} file protetti da password, non rinominati:")
        for nome in cifrati:
            print(f"  - {nome}")

    if scaduti:
        print(f"\n{len(scaduti)} file saltati per timeout (>{args.timeout:g}s):")
        for nome in scaduti:
            print(f"  - {nome}")
        print("Potrebbero avere una struttura interna molto danneggiata. Prova ad aumentare --timeout se vuoi ritentarli con più tempo.")

    if args.dry_run:
        print("\nQuesta era solo un'anteprima. Rilancia senza --dry-run per rinominare davvero.")


if __name__ == "__main__":
    main()
