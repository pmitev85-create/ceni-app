#!/usr/bin/env python3
"""Добавя или маха продукт от ceni/spisak.csv според попълнен формуляр (GitHub issue).

Пуска се от .github/workflows/spisak-ot-formular.yml. Чете тялото на issue-то от
файла в $GITHUB_EVENT_PATH и пише резултата (текст за отговор) в ceni/.otgovor.md.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
from pathlib import Path

PAPKA = Path(__file__).resolve().parent
SPISAK = PAPKA / "spisak.csv"
OTGOVOR = PAPKA / ".otgovor.md"
KOLONI = ["Продукт", "Категории КЗП", "Думи (по желание)", "Думи за Kaufland", "Без думи", "Количество", "Мярка"]


def poleta(tyalo: str) -> dict[str, str]:
    """Формулярите в GitHub се записват като „### Заглавие\\n\\nстойност“."""
    rezultat = {}
    for chast in re.split(r"^###\s+", tyalo or "", flags=re.M)[1:]:
        zaglavie, _, stoinost = chast.partition("\n")
        stoinost = stoinost.strip()
        if stoinost == "_No response_":
            stoinost = ""
        rezultat[zaglavie.strip()] = stoinost
    return rezultat


def chisto(tekst: str) -> str:
    return re.sub(r"\s+", " ", (tekst or "").replace(";", ",")).strip()


def procheti() -> list[dict[str, str]]:
    with SPISAK.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def zapishi(redove: list[dict[str, str]]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=KOLONI, delimiter=";", lineterminator="\n")
    w.writeheader()
    for r in redove:
        w.writerow({k: r.get(k, "") for k in KOLONI})
    SPISAK.write_text(buf.getvalue(), encoding="utf-8")


def main() -> int:
    sabitie = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    p = poleta(sabitie["issue"]["body"])
    deistvie = p.get("Какво да направя", "Добави").lower()
    ime = chisto(p.get("Продукт", ""))
    if not ime:  # празен формуляр – взимаме името от заглавието „Продукт: …“
        ime = chisto(re.sub(r"^\s*продукт\s*:\s*", "", sabitie["issue"].get("title", ""), flags=re.I))
    if not ime:
        OTGOVOR.write_text("❌ Не е попълнено име на продукта.", encoding="utf-8")
        return 1
    (PAPKA / ".ime.txt").write_text(ime, encoding="utf-8")
    redove = procheti()
    nalichni = {r["Продукт"].strip().lower(): r for r in redove}

    if deistvie.startswith("махни"):
        if ime.lower() not in nalichni:
            OTGOVOR.write_text(f"❌ Няма продукт „{ime}“ в списъка. Наличните са: "
                               + ", ".join(r["Продукт"] for r in redove), encoding="utf-8")
            return 1
        redove = [r for r in redove if r["Продукт"].strip().lower() != ime.lower()]
        zapishi(redove)
        OTGOVOR.write_text(f"✅ Махнах „{ime}“ от списъка. Таблицата е обновена.", encoding="utf-8")
        return 0

    dumi = chisto(p.get("Думи за търсене", "")).lower() or ime.lower()
    kolichestvo = chisto(p.get("Количество", "")).replace(",", ".") or "1"
    try:
        float(kolichestvo)
    except ValueError:
        kolichestvo = "1"
    merka = (p.get("Мярка", "") or "кг").strip().lower()
    if merka not in ("кг", "л", "бр"):
        merka = "кг"
    nov = {
        "Продукт": ime,
        "Категории КЗП": "",
        "Думи (по желание)": dumi,
        "Думи за Kaufland": dumi,
        "Без думи": chisto(p.get("Без думи", "")).lower(),
        "Количество": kolichestvo,
        "Мярка": merka,
    }
    if ime.lower() in nalichni:
        stari = nalichni[ime.lower()]
        stari.update({k: v for k, v in nov.items() if k != "Категории КЗП"})
        stari["Категории КЗП"] = ""   # категорията се намира наново по новите думи
        tekst = f"✅ Обнових „{ime}“ в списъка."
    else:
        redove.append(nov)
        tekst = f"✅ Добавих „{ime}“ в списъка (търся по: `{dumi}`)."
    zapishi(redove)
    OTGOVOR.write_text(tekst, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
