"""BLS 4.0 (Excel) in die kompakte Seed-Datei von FitPath umwandeln.

Läuft nicht im Container, sondern einmalig auf einem Rechner mit openpyxl:

    python -m venv venv && venv/bin/pip install openpyxl
    venv/bin/python tools/bls_convert.py BLS_4_0_Daten_2025_DE.xlsx seed/bls40.csv.gz

Quelle: https://www.blsdb.de/download (ZIP mit BLS_4_0_Daten_2025_DE.xlsx).
Lizenz der Daten: CC BY 4.0, Herausgeber Max Rubner-Institut.
Zitierweise: Max Rubner-Institut (2025): Bundeslebensmittelschlüssel (BLS),
Version 4.0 – Deutsche Nährstoffdatenbank. Karlsruhe. DOI: 10.25826/Data20251217-134202-0

Werte je 100 g essbarem Anteil. "<LOD", "<LOQ" und "TR" (Spuren) werden 0,
"-" (kein Wert) bleibt leer.
"""

import csv
import gzip
import sys

import openpyxl

# Spalte in der Seed-Datei -> EuroFIR-Code im BLS
COLUMNS = {
    "kcal": "ENERCC",
    "protein": "PROT625",
    "fat": "FAT",
    "satfat": "FASAT",
    "carbs": "CHO",
    "sugar": "SUGAR",
    "fiber": "FIBT",
    "alcohol": "ALC",
    "salt": "NACL",
}
ZERO_STRINGS = {"<LOD", "<LOQ", "<LOD or <LOQ", "TR"}


def value(raw):
    if raw is None or raw == "-":
        return ""
    if isinstance(raw, str):
        raw = raw.strip()
        if raw in ZERO_STRINGS:
            return "0"
        try:
            raw = float(raw.replace(",", "."))
        except ValueError:
            return ""
    return f"{float(raw):.3f}".rstrip("0").rstrip(".")


def main(src: str, dst: str) -> int:
    wb = openpyxl.load_workbook(src, read_only=True)
    rows = wb.worksheets[0].iter_rows(values_only=True)
    header = next(rows)
    idx = {}
    for key, code in COLUMNS.items():
        for i, col in enumerate(header):
            if col and str(col).split(" ")[0] == code and "[" in str(col):
                idx[key] = i
                break
        else:
            raise SystemExit(f"Spalte {code} nicht gefunden")
    n = 0
    with gzip.open(dst, "wt", encoding="utf-8", newline="") as fh:
        out = csv.writer(fh)
        out.writerow(["code", "name", *COLUMNS])
        for r in rows:
            if not r[0]:
                continue
            out.writerow([r[0], str(r[1]).strip(), *(value(r[i]) for i in idx.values())])
            n += 1
    print(f"{n} Lebensmittel nach {dst}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]))
