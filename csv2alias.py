#!/usr/bin/env python3
"""Converte un CSV esportato da Thunderbird in un file di alias per NeoMutt.

Uso:
    python3 csv2alias.py contatti.csv aliases

Il file di destinazione non viene mai sovrascritto: se esiste, lo script si
ferma. Ogni contatto con un indirizzo diventa una riga del tipo
    alias anna-rossi Anna Rossi <anna@esempio.org>
I contatti senza indirizzo vengono saltati.
"""
import csv
import os
import re
import sys
import unicodedata


def slug(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def find_column(headers, *candidates):
    lowered = {h.lower().strip(): h for h in headers}
    for cand in candidates:
        if cand in lowered:
            return lowered[cand]
    return None


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    if os.path.exists(dst):
        sys.exit(f"{dst} esiste gia': scegli un altro nome o spostalo.")

    with open(src, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        headers = reader.fieldnames or []

        mail_col = find_column(
            headers, "primary email", "e-mail address", "email address", "email", "e-mail"
        )
        if not mail_col:
            mail_col = next((h for h in headers if "mail" in h.lower()), None)
        if not mail_col:
            sys.exit("Non trovo la colonna con gli indirizzi. Colonne presenti:\n  "
                     + "\n  ".join(headers))
        display_col = find_column(headers, "display name")
        first_col = find_column(headers, "first name")
        last_col = find_column(headers, "last name")

        seen, written, skipped = set(), 0, 0
        lines = []
        for row in reader:
            mail = (row.get(mail_col) or "").strip()
            if not mail:
                skipped += 1
                continue
            name = (row.get(display_col) or "").strip() if display_col else ""
            if not name:
                first = (row.get(first_col) or "").strip() if first_col else ""
                last = (row.get(last_col) or "").strip() if last_col else ""
                name = f"{first} {last}".strip()
            key = slug(name) or slug(mail.split("@")[0]) or "contatto"
            base, n = key, 2
            while key in seen:
                key, n = f"{base}-{n}", n + 1
            seen.add(key)
            if re.search(r'[,;:()<>@"\\]', name):
                name = '"' + name.replace('"', "") + '"'
            lines.append(f"alias {key} {name} <{mail}>" if name else f"alias {key} <{mail}>")
            written += 1

    with open(dst, "w", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")
    print(f"Colonna indirizzi usata: {mail_col!r}")
    print(f"Alias scritti: {written}  |  contatti senza indirizzo saltati: {skipped}")
    print(f"File creato: {dst}")


if __name__ == "__main__":
    main()
