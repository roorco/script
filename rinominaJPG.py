import json, os, re, subprocess, sys
from collections import defaultdict
from pathlib import Path

cartella_radice = sys.argv[1]
applica = "--applica" in sys.argv
ESTENSIONI = {".jpg", ".jpeg", ".png", ".heic", ".cr2", ".raf"}

# Scandisce ricorsivamente tutte le sottocartelle
file_list = [str(p) for p in Path(cartella_radice).rglob("*")
             if p.is_file() and p.suffix.lower() in ESTENSIONI]

print(f"Trovati {len(file_list)} file in tutte le sottocartelle. Lettura metadati in corso...")

risultato = subprocess.run(
    ["exiftool", "-json", "-fast2", "-charset", "filename=utf8", "-Make", "-Model",
     "-DateTimeOriginal", "-CreateDate", "-FileModifyDate", "-@", "-"],
    input="\n".join(file_list), capture_output=True, text=True)
dati = json.loads(risultato.stdout)

FORMATO_DATA = re.compile(r"^\d{4}[:\-]\d{2}[:\-]\d{2}")

def data_valida(d):
    if not d or not FORMATO_DATA.match(str(d)) or str(d).startswith("0000"):
        return False
    anno = int(str(d)[:4])
    return 1990 <= anno <= 2100

def ottieni_sigla(make, model):
    lettere_model = re.sub(r"[^A-Za-z]", "", str(model)) if model else ""
    if len(lettere_model) >= 3:
        return lettere_model[:3].upper()
    lettere_make = re.sub(r"[^A-Za-z]", "", str(make)) if make else ""
    if lettere_make:
        return lettere_make[:3].upper()
    return "UNK"

gruppi = defaultdict(list)
n_senza_data = 0
n_senza_modello = 0

for d in dati:
    percorso = d["SourceFile"]
    make = d.get("Make")
    modello_raw = d.get("Model")
    data = d.get("DateTimeOriginal") or d.get("CreateDate")
    fonte = "DateTimeOriginal/CreateDate"

    if not data_valida(data):
        data = d.get("FileModifyDate")
        fonte = "FileModifyDate (fallback)"

    if not data_valida(data):
        giorno_breve = "000000"
        n_senza_data += 1
    else:
        cifre = re.sub(r"[:\-]", "", str(data)[:10])
        giorno_breve = cifre[2:]

    sigla_gruppo = ottieni_sigla(make, modello_raw)
    if sigla_gruppo == "UNK":
        n_senza_modello += 1

    cartella_file = os.path.dirname(percorso)
    stem = os.path.splitext(os.path.basename(percorso))[0].lower()
    # La chiave del gruppo NON include più la cartella: così due file con lo
    # stesso nome in cartelle diverse, ma con stesso stem/sigla/data (o
    # entrambi senza data), vengono considerati la stessa "foto" e ricevono
    # lo stesso numero, così come già avveniva per le coppie RAW+JPG.
    gruppi[(stem, sigla_gruppo, giorno_breve)].append(percorso)

print(f"\n{n_senza_data} file senza data valida/plausibile (raggruppati sotto 000000), "
      f"{n_senza_modello} con sigla UNK, "
      f"{len(gruppi)} foto da rinominare (contando coppie RAW+JPG come una).\n")

chiavi = sorted(gruppi, key=lambda k: (k[2], k[0]))

conteggio_gruppi = defaultdict(int)
for chiave in chiavi:
    _, sigla, giorno_breve = chiave
    conteggio_gruppi[(sigla, giorno_breve)] += 1

contatori = defaultdict(int)

for chiave in chiavi:
    stem, sigla, giorno_breve = chiave
    contatori[(sigla, giorno_breve)] += 1
    i = contatori[(sigla, giorno_breve)]

    totale_gruppo = conteggio_gruppi[(sigla, giorno_breve)]
    cifre = max(3, len(str(totale_gruppo)))

    for percorso in gruppi[chiave]:
        cartella_file = os.path.dirname(percorso)
        ext = os.path.splitext(percorso)[1].lower()
        nuovo = f"{sigla}_{giorno_breve}_{i:0{cifre}d}{ext}"
        destinazione = os.path.join(cartella_file, nuovo)
        print(f"{percorso} -> {destinazione}")
        if applica:
            if os.path.exists(destinazione):
                print("  ATTENZIONE: esiste già, non rinominato")
            else:
                os.rename(percorso, destinazione)
