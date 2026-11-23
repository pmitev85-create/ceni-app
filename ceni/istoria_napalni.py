#!/usr/bin/env python3
"""Попълва историята на цените от всички налични дневни архиви на КЗП (обикновено ~2 седмици назад).
Пуска се веднъж; пропуска дните, които вече са записани. Дните се обработват по ред."""
from __future__ import annotations

import io
import re
import sys
import time
import zipfile

import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import istoria  # noqa: E402
import obnovi  # noqa: E402


def main() -> int:
    nastr = obnovi.zaredi_nastroiki()
    sesia = requests.Session()
    sesia.headers.update(obnovi.HEADERS)
    html = sesia.get(obnovi.KZP_OPENDATA, timeout=60).text
    dni = sorted(set(re.findall(r"/opendata_files/(\d{4}-\d{2}-\d{2})\.zip", html)))
    gotovi = istoria.zapisani_dni("kzp")
    posleden = max(gotovi) if gotovi else ""
    for den in dni:
        if den in gotovi or den < posleden:
            continue
        for opit in range(4):
            try:
                r = sesia.get(f"{obnovi.KZP_BASE}/opendata_files/{den}.zip", timeout=300)
                zipfile.ZipFile(io.BytesIO(r.content)).testzip()
                break
            except (requests.RequestException, zipfile.BadZipFile):
                time.sleep(10 * (opit + 1))
        else:
            print(f"{den}: не се изтегли, пропускам")
            continue
        artikuli, _ = obnovi.kzp_artikuli(r.content, None, nastr.get("grad", ""), nastr.get("ekatte", ""))
        zapisi = {istoria.kluch("k", v, a.ime): istoria.stoinost(a.redovna, a.cena)
                  for v, lst in artikuli.items() for a in lst}
        n = istoria.zapishi("kzp", den, zapisi)
        print(f"{den}: {len(zapisi)} артикула, {n} промени")
    return 0


if __name__ == "__main__":
    sys.exit(main())
