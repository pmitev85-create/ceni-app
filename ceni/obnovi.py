#!/usr/bin/env python3
"""Обновява таблицата за сравнение на цени (ceni/ceni.xlsx).

Източници:
  * КЗП „Колко струва“ – отворени данни (дневни цени по магазини за веригите,
    подали информация): https://kolkostruva.bg/opendata
  * Kaufland – актуалните седмични оферти от kaufland.bg (Kaufland не подава
    данни към КЗП, затова за него има само промоционални цени).

Пускане:  python ceni/obnovi.py
"""
from __future__ import annotations

import csv
import io
import json
import re
import statistics
import sys
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterator

import requests
from bs4 import BeautifulSoup
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

PAPKA = Path(__file__).resolve().parent
SPISAK = PAPKA / "spisak.csv"
NASTROIKI = PAPKA / "nastroiki.json"
IZHOD = PAPKA / "ceni.xlsx"
APP_DANNI = PAPKA.parent / "app" / "data" / "ceni.json"

KZP_OPENDATA = "https://kolkostruva.bg/opendata"
KZP_BASE = "https://kolkostruva.bg"
KAUFLAND_URL = "https://www.kaufland.bg/aktualni-predlozheniya/oferti.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (price-comparison script; personal use)"}

# Категории, в които стоката се продава на тегло (цената е за кг,
# освен ако в името не е посочена точна разфасовка).
NA_TEGLO = {8, 13, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 29, 30,
            50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62}
# Стандартна разфасовка, когато в името няма грамаж (напр. „Захар“ в Lidl).
STANDARTNO = {6: (1, "л"), 7: (0.4, "кг"), 31: (10, "бр"), 32: (10, "бр"), 33: (1, "кг"),
              34: (1, "кг"), 35: (1, "кг"), 38: (1, "кг"), 39: (1, "кг"),
              40: (1, "кг"), 41: (1, "кг"), 42: (1, "л")}

# Кратки имена на веригите (по началото на името на файла в архива на КЗП).
IMENA_VERIGI = {
    "лидл": "Lidl", "метро": "Metro", "билла": "Billa", "фантастико": "Fantastico",
    "t market": "T Market", "kaufland": "Kaufland", "кауфланд": "Kaufland",
}

SOFIA_TZ = timezone(timedelta(hours=2))


# --------------------------------------------------------------------------- #
# Помощни функции
# --------------------------------------------------------------------------- #
def kratko_ime(ime_na_fail: str) -> str:
    osnova = ime_na_fail.rsplit("_", 1)[0]
    osnova = osnova.split(" (")[0].strip()
    nisko = osnova.lower()
    for kluch, ime in IMENA_VERIGI.items():
        if nisko.startswith(kluch):
            return ime
    return osnova


def chislo(tekst: str) -> float | None:
    tekst = (tekst or "").strip().replace(",", ".").replace("€", "").strip()
    try:
        stoinost = float(tekst)
    except ValueError:
        return None
    return stoinost if stoinost > 0 else None


def _duma(d: str) -> str:
    """Цяла дума; „*“ накрая позволява произволно окончание (домат* → домати, доматен…)."""
    if d.endswith("*"):
        return r"(?<![a-zа-я0-9])" + re.escape(d[:-1])
    return r"(?<![a-zа-я0-9])" + re.escape(d) + r"(?![a-zа-я0-9])"


def sadarzha(tekst: str, izraz: str) -> bool:
    """„a b|c“ означава (a И b) ИЛИ c. Търсят се цели думи (или с * за окончание)."""
    if not izraz.strip():
        return True
    tekst = tekst.lower().replace("ё", "е")
    for variant in izraz.lower().split("|"):
        dumi = variant.split()
        if dumi and all(re.search(_duma(d), tekst) for d in dumi):
            return True
    return False


_MERKI = {"кг": ("кг", 1), "kg": ("кг", 1), "г": ("кг", 0.001), "гр": ("кг", 0.001),
          "gr": ("кг", 0.001), "g": ("кг", 0.001), "л": ("л", 1), "l": ("л", 1),
          "мл": ("л", 0.001), "ml": ("л", 0.001), "бр": ("бр", 1)}
_ED = r"(кг|kg|гр|gr|г|g|мл|ml|л|l|бр)(?![a-zа-я])"


@dataclass
class Razfasovka:
    kolichestvo: float
    merka: str        # кг / л / бр
    priblizitelno: bool


def razfasovki(ime: str) -> list[Razfasovka]:
    t = ime.lower().replace(",", ".")
    t = re.sub(r"(\d)\.\s+(\d)", r"\1.\2", t)            # „1. 5 л“ → „1.5 л“
    t = re.sub(r"(\d)\s*[xх×]\s*(\d)", r"\1x\2", t)
    rezultat: list[Razfasovka] = []
    zaeti: list[tuple[int, int]] = []
    for m in re.finditer(r"(\d+)x(\d+(?:\.\d+)?)\s*" + _ED, t):
        merka, k = _MERKI[m.group(3)]
        rezultat.append(Razfasovka(int(m.group(1)) * float(m.group(2)) * k, merka, False))
        zaeti.append(m.span())
    for m in re.finditer(r"(?<![\d.x/])(\d+(?:\.\d+)?)\s*" + _ED, t):
        if any(a <= m.start() < b for a, b in zaeti):
            continue
        merka, k = _MERKI[m.group(2)]
        predi = t[max(0, m.start() - 8):m.start()]
        priblizitelno = bool(re.search(r"(~|ок\.?\s*$|около\s*$|\d\s*[-–]\s*$|\+\s*$)", predi))
        # диапазон „1,2-2,0 кг“
        if re.match(r"\s*-\s*\d", t[m.end(1):m.end(1) + 4]):
            priblizitelno = True
        rezultat.append(Razfasovka(float(m.group(1)) * k, merka, priblizitelno))
    # „ЯЙЦА M10“ / „L6“
    for m in re.finditer(r"(?<![a-zа-я])[mlмл](\d{1,2})(?!\d)", t):
        if "яйц" in t:
            rezultat.append(Razfasovka(float(m.group(1)), "бр", False))
    return rezultat


def cena_za_merka(ime: str, cena: float, merka: str, kategoria: int | None,
                  edinica_kaufland: str = "") -> tuple[float | None, str]:
    """Връща (цена за мярка, описание на разфасовката)."""
    tekst = f"{ime} {edinica_kaufland}"
    vsichki_razf = razfasovki(tekst)
    razf = [r for r in vsichki_razf if r.merka == merka]
    druga_merka = any(r.merka != merka and r.merka != "бр" for r in vsichki_razf)
    tochni = [r for r in razf if not r.priblizitelno and r.kolichestvo > 0]
    if edinica_kaufland.strip().lower().rstrip(".") in ("кг", "kg") and merka == "кг":
        return cena, "за кг"
    if tochni:
        r = tochni[0]
        return cena / r.kolichestvo, f"{r.kolichestvo:g} {merka}"
    if merka == "кг" and kategoria in NA_TEGLO:
        return cena, "за кг"
    if razf and merka == "кг":  # само приблизителен грамаж → продава се на кг
        return cena, "за кг"
    if kategoria in STANDARTNO and STANDARTNO[kategoria][1] == merka and not druga_merka:
        kol = STANDARTNO[kategoria][0]
        return cena / kol, f"{kol:g} {merka} (станд.)"
    if merka == "бр" and not razf:
        return cena, "1 бр"
    return None, "неизвестна"


# --------------------------------------------------------------------------- #
# Входни данни
# --------------------------------------------------------------------------- #
@dataclass
class Produkt:
    ime: str
    kategorii: set[int]
    dumi: str
    dumi_kaufland: str
    bez: str
    kolichestvo: float
    merka: str


def zaredi_spisak() -> list[Produkt]:
    produkti = []
    with SPISAK.open(encoding="utf-8-sig") as f:
        for red in csv.DictReader(f, delimiter=";"):
            ime = (red.get("Продукт") or "").strip()
            if not ime or ime.startswith("#"):
                continue
            kat = {int(x) for x in re.findall(r"\d+", red.get("Категории КЗП") or "")}
            produkti.append(Produkt(
                ime=ime, kategorii=kat,
                dumi=(red.get("Думи (по желание)") or "").strip(),
                dumi_kaufland=(red.get("Думи за Kaufland") or "").strip(),
                bez=(red.get("Без думи") or "").strip(),
                kolichestvo=chislo(red.get("Количество") or "1") or 1,
                merka=(red.get("Мярка") or "кг").strip().lower().rstrip("."),
            ))
    return produkti


def zaredi_nastroiki() -> dict:
    nastr = {"grad": "", "osnovni_verigi": ["Lidl", "Kaufland", "Metro"],
             "drugi_verigi": ["Billa", "Fantastico", "T Market"]}
    if NASTROIKI.exists():
        nastr.update(json.loads(NASTROIKI.read_text(encoding="utf-8")))
    return nastr


# --------------------------------------------------------------------------- #
# КЗП „Колко струва“
# --------------------------------------------------------------------------- #
def kzp_arhiv(sesia: requests.Session) -> tuple[str, bytes]:
    html = sesia.get(KZP_OPENDATA, timeout=60).text
    vrazki = sorted(set(re.findall(r'href="(/opendata_files/(\d{4}-\d{2}-\d{2})\.zip)"', html)),
                    key=lambda x: x[1], reverse=True)
    if not vrazki:
        raise RuntimeError("Не намерих архиви на страницата с отворени данни на КЗП.")
    for put, data in vrazki[:3]:
        for opit in range(1, 5):
            try:
                r = sesia.get(KZP_BASE + put, timeout=300)
                if r.ok and r.content[:2] == b"PK":
                    zipfile.ZipFile(io.BytesIO(r.content)).testzip()
                    return data, r.content
                print(f"  архивът за {data}: отговор {r.status_code}")
                break
            except (requests.RequestException, zipfile.BadZipFile) as e:
                print(f"  архивът за {data}, опит {opit}: {e.__class__.__name__}")
                time.sleep(10 * opit)
        print("  пробвам предишния ден")
    raise RuntimeError("Нито един от последните архиви на КЗП не се изтегли.")


@dataclass
class Artikul:
    veriga_a: str
    ime: str
    kategoria: int | None
    cena: float            # цена, която плащаш (промо, ако има)
    redovna: float | None
    promo: bool
    magazini: int
    cena_merka: float | None = None
    razfasovka: str = ""
    iztochnik: str = ""
    kod: str = ""


def _redove_csv(f) -> "Iterator[dict[str, str]]":
    """Чете CSV от КЗП; някои вериги ползват „;“ или имат интервали/кавички в заглавията."""
    tekst = io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace")
    parvi = tekst.readline()
    razdelitel = ";" if parvi.count(";") > parvi.count(",") else ","
    zaglavia = [h.strip().strip('"').strip() for h in next(csv.reader([parvi], delimiter=razdelitel))]
    for red in csv.reader(tekst, delimiter=razdelitel):
        yield {z: (s.strip().strip('"') if s else s) for z, s in zip(zaglavia, red)}


def kzp_artikuli(arhiv: bytes, kategorii: set[int] | None, grad: str, ekatte: str = ""
                 ) -> tuple[dict[str, list[Artikul]], dict[str, int]]:
    """kategorii=None → всички категории."""
    grad = grad.strip().lower()
    ekatte = str(ekatte).strip().lstrip("0")
    po_verigi: dict[str, list[Artikul]] = defaultdict(list)
    magazini_v_grada: dict[str, int] = {}
    with zipfile.ZipFile(io.BytesIO(arhiv)) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith(".csv"):
                continue
            ime_fail = Path(info.filename).name
            veriga = kratko_ime(ime_fail[:-4])
            ceni: dict[str, list[tuple[float, bool, float | None]]] = defaultdict(list)
            kat_na: dict[str, int] = {}
            kod_na: dict[str, str] = {}
            obekti = set()
            with z.open(info) as f:
                for red in _redove_csv(f):
                    try:
                        kat = int(float((red.get("Категория") or "").strip()))
                    except ValueError:
                        continue
                    if kategorii is not None and kat not in kategorii:
                        continue
                    obekt = (red.get("Търговски обект") or "")
                    if grad or ekatte:
                        kod = (red.get("Населено място") or "").strip().lstrip("0")
                        if not ((ekatte and kod == ekatte) or (grad and grad in obekt.lower())):
                            continue
                    redovna = chislo(red.get("Цена на дребно"))
                    promo = chislo(red.get("Цена в промоция"))
                    if redovna is None and promo is None:
                        continue
                    ima_promo = promo is not None and (redovna is None or promo < redovna)
                    plashtash = promo if ima_promo else redovna
                    ime = re.sub(r"\s+", " ", (red.get("Наименование на продукта") or "")).strip(' ";')
                    ceni[ime].append((plashtash, ima_promo, redovna))
                    kat_na[ime] = kat
                    kod_na[ime] = (red.get("Код на продукта") or "").strip()
                    obekti.add(obekt)
            magazini_v_grada[veriga] = magazini_v_grada.get(veriga, 0) + len(obekti)
            for ime, spisak in ceni.items():
                (plashtash, ima_promo), _ = Counter((c, p) for c, p, _ in spisak).most_common(1)[0]
                redovni = [r for _, _, r in spisak if r]
                redovna = Counter(redovni).most_common(1)[0][0] if redovni else None
                po_verigi[veriga].append(Artikul(veriga, ime, kat_na[ime], plashtash, redovna,
                                                 ima_promo, len(spisak), iztochnik="КЗП",
                                                 kod=kod_na.get(ime, "")))
    return po_verigi, magazini_v_grada


# --------------------------------------------------------------------------- #
# Kaufland
# --------------------------------------------------------------------------- #
@dataclass
class OfertaKaufland:
    sekcia: str
    zaglavie: str
    podzaglavie: str
    razfasovka: str
    cena: float
    stara: float | None
    otstapka: str
    period: str


def kaufland_oferti(sesia: requests.Session) -> list[OfertaKaufland]:
    r = sesia.get(KAUFLAND_URL, timeout=90)
    r.raise_for_status()
    s = BeautifulSoup(r.text, "html.parser")

    def tx(el, sel):
        e = el.select_one(sel)
        return re.sub(r"\s+", " ", e.get_text(" ", strip=True)) if e else ""

    oferti, vidiani = [], set()
    for sekcia in s.select(".k-product-section"):
        zaglavie_sekcia = tx(sekcia, ".k-product-section__headline") or tx(sekcia, "h2")
        period = ""
        m = re.search(r"\d{2}\.\d{2}\.\d{4}\s*-\s*\d{2}\.\d{2}\.\d{4}", sekcia.get_text(" ", strip=True)[:300])
        if m:
            period = m.group(0)
        for t in sekcia.select("a.k-product-tile"):
            cena = chislo(tx(t, ".k-price-tag__price"))
            if cena is None:
                continue
            o = OfertaKaufland(
                sekcia=zaglavie_sekcia, zaglavie=tx(t, ".k-product-tile__title"),
                podzaglavie=tx(t, ".k-product-tile__subtitle"),
                razfasovka=tx(t, ".k-product-tile__unit-price"), cena=cena,
                stara=chislo(tx(t, ".k-price-tag__old-price")),
                otstapka=tx(t, ".k-price-tag__discount"), period=period)
            kluch = (o.zaglavie, o.podzaglavie, o.razfasovka, o.cena)
            if kluch in vidiani:
                continue
            vidiani.add(kluch)
            oferti.append(o)
    return oferti


# --------------------------------------------------------------------------- #
# Сравнение
# --------------------------------------------------------------------------- #
def avto_kategorii(p: Produkt, artikuli: dict[str, list[Artikul]]) -> set[int]:
    """За продукт без категория: най-честата категория сред артикулите, които съдържат думите."""
    if not p.dumi:
        return set()
    broi = Counter(a.kategoria for lst in artikuli.values() for a in lst
                   if sadarzha(a.ime, p.dumi) and not (p.bez and sadarzha(a.ime, p.bez)))
    if not broi:
        return set()
    nai, n = broi.most_common(1)[0]
    # добави и близки по честота категории (напр. 10 и 11 за кашкавал)
    return {k for k, c in broi.items() if c >= max(3, n * 0.5)} or {nai}


def kandidati(p: Produkt, artikuli: list[Artikul]) -> list[Artikul]:
    izbrani = []
    for a in artikuli:
        if a.kategoria not in p.kategorii:
            continue
        if not sadarzha(a.ime, p.dumi) or (p.bez and sadarzha(a.ime, p.bez)):
            continue
        cm, razf = cena_za_merka(a.ime, a.cena, p.merka, a.kategoria)
        izbrani.append(Artikul(**{**a.__dict__, "cena_merka": cm, "razfasovka": razf}))
    return podredi(izbrani)


def kandidati_kaufland(p: Produkt, oferti: list[OfertaKaufland]) -> list[Artikul]:
    if not p.dumi_kaufland:
        return []
    izbrani = []
    plodove = bool(p.kategorii & set(range(50, 62)))
    meso = bool(p.kategorii & set(range(15, 27)))
    for o in oferti:
        tekst = f"{o.zaglavie} {o.podzaglavie}"
        sekcia = o.sekcia.lower()
        if plodove and not ("плодове" in sekcia or "вкус" in sekcia):
            continue
        if meso and not ("месо" in sekcia or "вкус" in sekcia):
            continue
        if not sadarzha(tekst, p.dumi_kaufland) or (p.bez and sadarzha(tekst, p.bez)):
            continue
        if p.dumi and not sadarzha(tekst, p.dumi):
            continue
        kat = next(iter(p.kategorii)) if p.kategorii else None
        cm, razf = cena_za_merka(tekst, o.cena, p.merka, None, o.razfasovka)
        if razf == "неизвестна" and kat in NA_TEGLO and not o.razfasovka:
            cm, razf = o.cena, "за кг"
        ime = f"{o.zaglavie} – {o.podzaglavie}".strip(" –") + (f" ({o.razfasovka})" if o.razfasovka else "")
        izbrani.append(Artikul("Kaufland", ime, None, o.cena, o.stara, True, 0,
                               cena_merka=cm, razfasovka=razf, iztochnik="kaufland.bg"))
    return podredi(izbrani)


def proveri_za_greshki(vsichki: dict[str, list[Artikul]]) -> None:
    """Маха нереалистични цени за мярка (напр. едро-разфасовки, обявени с цена за кг)."""
    stoinosti = [a.cena_merka for lst in vsichki.values() for a in lst[:3] if a.cena_merka]
    if len(stoinosti) < 4:
        return
    med = statistics.median(stoinosti)
    for v, lst in vsichki.items():
        for a in lst:
            if a.cena_merka is None:
                continue
            m = re.match(r"([\d.]+)", a.razfasovka)
            razmer = float(m.group(1)) if m and "станд" not in a.razfasovka else 0
            # едра разфасовка (3+ кг/л) с подозрително ниска цена → цената е за кг/л
            if razmer >= 3 and a.cena_merka < 0.5 * med and 0.2 * med <= a.cena <= 3 * med:
                a.cena_merka, a.razfasovka = a.cena, f"{a.razfasovka}, цена за кг/л"
            elif a.cena_merka < 0.2 * med:
                golyama = razmer >= 1.5
                if golyama and 0.2 * med <= a.cena <= 3 * med:
                    a.cena_merka, a.razfasovka = a.cena, f"{a.razfasovka}, цена за кг/л"
                else:
                    a.cena_merka, a.razfasovka = None, f"{a.razfasovka} (съмнителна)"
            elif a.cena_merka > 5 * med:
                a.cena_merka, a.razfasovka = None, f"{a.razfasovka} (съмнителна)"
        vsichki[v] = podredi(lst)


def e_barkod(kod: str) -> bool:
    if not re.fullmatch(r"\d{13}", kod or ""):
        return False
    cifri = [int(c) for c in kod]
    suma = sum(v * (3 if i % 2 == 0 else 1) for i, v in enumerate(reversed(cifri[:-1])))
    return (10 - suma % 10) % 10 == cifri[-1]


def prirodna_cena(ime: str, cena: float, kategoria: int | None, edinica: str = "") -> tuple[float | None, str]:
    """Цена за естествената мярка на артикула (кг / л / бр), ако може да се определи."""
    tekst = f"{ime} {edinica}"
    razf = razfasovki(tekst)
    tochni = [r for r in razf if not r.priblizitelno and r.kolichestvo > 0]
    ed = edinica.strip().lower().rstrip(".")
    if ed in ("кг", "kg"):
        return cena, "кг"
    if kategoria in NA_TEGLO and not tochni:
        return cena, "кг"
    if tochni:
        r = tochni[0]
        return cena / r.kolichestvo, r.merka
    if razf and razf[0].merka == "кг":
        return cena, "кг"
    if kategoria in STANDARTNO:
        kol, merka = STANDARTNO[kategoria]
        return cena / kol, merka
    return None, ""


def razmer_na(tekst: str) -> float | None:
    """Точната разфасовка (в кг / л / бр), ако е написана в името."""
    tochni = [r for r in razfasovki(tekst) if not r.priblizitelno and r.kolichestvo > 0]
    return round(tochni[0].kolichestvo, 3) if tochni else None


def izvadi_json(produkti, rezultati, verigi_koloni, artikuli, kaufland, data_kzp, grad, magazini) -> None:
    """Данни за мобилното приложение: сравнението по списъка + всички артикули в града за търсене."""
    def art(a: Artikul | None, veriga: str | None = None) -> dict | None:
        if not a:
            return None
        d = {"ime": a.ime, "cena": round(a.cena, 2), "promo": a.promo,
             "cm": round(a.cena_merka, 2) if a.cena_merka is not None else None, "razf": a.razfasovka}
        if a.redovna and a.promo:
            d["redovna"] = round(a.redovna, 2)
        if veriga:
            d["veriga"] = veriga
        return d

    spisak = []
    for p in produkti:
        r = rezultati[p.ime]
        spisak.append({
            "ime": p.ime, "merka": p.merka, "kolichestvo": p.kolichestvo,
            "ceni": {v: art(r.get(v)) for v in verigi_koloni if r.get(v) and r[v].cena_merka is not None},
            "drugi": art(r.get("__drugi__"), r["__drugi__"].veriga_a) if r.get("__drugi__") else None,
        })

    imena_verigi = sorted(artikuli, key=lambda v: (v not in verigi_koloni, verigi_koloni.index(v) if v in verigi_koloni else 0, v))
    if "Kaufland" not in imena_verigi:
        imena_verigi.insert(min(1, len(imena_verigi)), "Kaufland")
    vi = {v: i for i, v in enumerate(imena_verigi)}
    index = []
    for v, lst in artikuli.items():
        for a in lst:
            cm, merka = prirodna_cena(a.ime, a.cena, a.kategoria)
            red = [vi[v], a.ime, round(a.cena, 2), round(cm, 2) if cm else None, merka, 1 if a.promo else 0,
                   round(a.redovna, 2) if a.redovna else None, a.kategoria, razmer_na(a.ime)]
            if e_barkod(a.kod):
                red.append(a.kod)
            index.append(red)
    for o in kaufland:
        ime = f"{o.zaglavie} – {o.podzaglavie}".strip(" –") + (f" ({o.razfasovka})" if o.razfasovka else "")
        cm, merka = prirodna_cena(f"{o.zaglavie} {o.podzaglavie}", o.cena, None, o.razfasovka)
        index.append([vi["Kaufland"], ime, round(o.cena, 2), round(cm, 2) if cm else None, merka, 1,
                      round(o.stara, 2) if o.stara else None, None,
                      razmer_na(f"{o.zaglavie} {o.podzaglavie} {o.razfasovka}")])

    dannni = {
        "data": data_kzp, "obnoveno": datetime.now(SOFIA_TZ).strftime("%d.%m.%Y %H:%M"),
        "grad": grad or "цялата страна", "verigi": verigi_koloni,
        "magazini": {v: magazini.get(v, 0) for v in imena_verigi},
        "spisak": spisak,
        "index": {"verigi": imena_verigi,
                  "poleta": ["veriga", "ime", "cena", "cena_merka", "merka", "promo", "redovna", "kategoria", "razmer", "barkod"],
                  "artikuli": index},
    }
    APP_DANNI.parent.mkdir(parents=True, exist_ok=True)
    APP_DANNI.write_text(json.dumps(dannni, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  данни за приложението: {APP_DANNI} ({APP_DANNI.stat().st_size / 1e6:.2f} MB, {len(index)} артикула)")


def podredi(spisak: list[Artikul]) -> list[Artikul]:
    return sorted(spisak, key=lambda a: (a.cena_merka is None, a.cena_merka or a.cena, a.cena))


# --------------------------------------------------------------------------- #
# Excel
# --------------------------------------------------------------------------- #
SHRIFT = "Arial"
ZAGLAVIE_FILL = PatternFill("solid", fgColor="1F4E78")
ZAGLAVIE_FONT = Font(name=SHRIFT, bold=True, color="FFFFFF")
VAVEDI_FILL = PatternFill("solid", fgColor="FFF2CC")
ZELENO = PatternFill("solid", fgColor="C6EFCE")
TANKA = Side(style="thin", color="BFBFBF")
RAMKA = Border(left=TANKA, right=TANKA, top=TANKA, bottom=TANKA)
EVRO = '#,##0.00 "€"'


def zaglavie_red(ws, red, stoinosti, shirini=None):
    for i, s in enumerate(stoinosti, 1):
        c = ws.cell(row=red, column=i, value=s)
        c.font, c.fill, c.border = ZAGLAVIE_FONT, ZAGLAVIE_FILL, RAMKA
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if shirini:
        for i, w in enumerate(shirini, 1):
            ws.column_dimensions[get_column_letter(i)].width = w


def obshti_stilove(ws):
    for red in ws.iter_rows():
        for c in red:
            if c.font is None or c.font.name != SHRIFT:
                c.font = Font(name=SHRIFT, bold=c.font.bold if c.font else False,
                              color=c.font.color if c.font else None,
                              size=c.font.size if c.font else 11,
                              italic=c.font.italic if c.font else False)


def napravi_excel(produkti, rezultati, verigi_koloni, kaufland, data_kzp, grad, magazini, greshki):
    wb = Workbook()
    sega = datetime.now(SOFIA_TZ).strftime("%d.%m.%Y %H:%M")

    # ---------------- Сравнение ----------------
    ws = wb.active
    ws.title = "Сравнение"
    ws["A1"] = "Сравнение на цени – моята кошница"
    ws["A1"].font = Font(name=SHRIFT, bold=True, size=16, color="1F4E78")
    ws["A2"] = (f"Цени от КЗП „Колко струва“ към {data_kzp} · оферти Kaufland · обновено {sega} · "
                f"град: {grad or 'всички (типична цена в страната)'}")
    ws["A2"].font = Font(name=SHRIFT, italic=True, color="595959")
    ws["A3"] = ("Цените са в € за мярката (кг / л / бр). Зелено = най-ниска цена. "
                "Удебелено = промоция. Kaufland = само текущи оферти (не подава данни към КЗП).")
    ws["A3"].font = Font(name=SHRIFT, size=9, color="595959")

    vsichki_v = verigi_koloni + ["Друга верига"]
    koloni = (["Продукт", "Мярка", "Количество"] + verigi_koloni
              + ["Друга верига", "Коя е", "Най-ниска цена", "Къде", "Най-евтин артикул (марка)", "Сума за количеството", ""]
              + [f"Артикул – {v}" for v in vsichki_v])
    H = 5
    zaglavie_red(ws, H, koloni, [22, 8, 13] + [11] * len(verigi_koloni) + [11, 22, 12, 16, 42, 14, 2]
                 + [38] * len(vsichki_v))
    pv = 4                                   # първа колона с цена (D)
    pp = pv + len(verigi_koloni)             # „Друга верига“
    kk = pp + 1                              # „Коя е“
    km = kk + 1                              # „Най-ниска цена“
    kd = km + 1                              # „Къде“
    ka = kd + 1                              # най-евтин артикул
    ks = ka + 1                              # сума
    ab = ks + 2                              # блок с имената на артикулите по вериги
    ws.cell(row=H, column=ks + 1).fill = PatternFill(fill_type=None)
    L = get_column_letter
    for i, p in enumerate(produkti):
        r = H + 1 + i
        ws.cell(row=r, column=1, value=p.ime).font = Font(name=SHRIFT, bold=True)
        ws.cell(row=r, column=2, value=p.merka)
        c = ws.cell(row=r, column=3, value=p.kolichestvo)
        c.fill = VAVEDI_FILL
        c.comment = Comment("Количество, което обикновено купуваш (в мярката от колона B). Може да го промениш.", "таблица")
        for j, v in enumerate(verigi_koloni + ["__drugi__"]):
            a = rezultati[p.ime].get(v)
            c = ws.cell(row=r, column=pv + j)
            if a and a.cena_merka is not None:
                c.value = round(a.cena_merka, 2)
                c.number_format = EVRO
                c.font = Font(name=SHRIFT, bold=a.promo)
                belezhka = f"{a.ime}\n{a.cena:.2f} € ({a.razfasovka})"
                if a.promo and a.redovna:
                    belezhka += f"\nПромоция, редовна цена {a.redovna:.2f} €"
                c.comment = Comment(belezhka, "таблица", width=260, height=90)
            if v == "__drugi__" and a:
                ws.cell(row=r, column=kk, value=a.veriga_a)
            if a and a.cena_merka is not None:
                ime = a.ime + (" (промоция)" if a.promo else "")
                ws.cell(row=r, column=ab + j, value=ime).border = RAMKA
        obh = f"{L(pv)}{r}:{L(pp)}{r}"
        ws.cell(row=r, column=km, value=f'=IF(COUNT({obh})=0,"",MIN({obh}))').number_format = EVRO
        ws.cell(row=r, column=kd, value=(
            f'=IF({L(km)}{r}="","",IF(MATCH({L(km)}{r},{obh},0)={pp - pv + 1},{L(kk)}{r},'
            f'INDEX(${L(pv)}${H}:${L(pp)}${H},MATCH({L(km)}{r},{obh},0))))'))
        imena = f"{L(ab)}{r}:{L(ab + len(vsichki_v) - 1)}{r}"
        ws.cell(row=r, column=ka, value=f'=IF({L(km)}{r}="","",INDEX({imena},MATCH({L(km)}{r},{obh},0)))')
        ws.cell(row=r, column=ks, value=f'=IF({L(km)}{r}="","",{L(km)}{r}*C{r})').number_format = EVRO
        for col in range(1, ks + 1):
            ws.cell(row=r, column=col).border = RAMKA
    posleden = H + len(produkti)
    obhvat = f"{L(pv)}{H + 1}:{L(pp)}{posleden}"
    ws.conditional_formatting.add(obhvat, FormulaRule(
        formula=[f'AND({L(pv)}{H + 1}<>"",{L(pv)}{H + 1}=MIN(${L(pv)}{H + 1}:${L(pp)}{H + 1}))'], fill=ZELENO))
    r = posleden + 1
    ws.cell(row=r, column=1, value="Общо при най-ниските цени").font = Font(name=SHRIFT, bold=True)
    c = ws.cell(row=r, column=ks, value=f"=SUM({L(ks)}{H + 1}:{L(ks)}{posleden})")
    c.number_format, c.font = EVRO, Font(name=SHRIFT, bold=True)
    ws.freeze_panes = ws.cell(row=H + 1, column=2)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    # ---------------- Кошница по вериги ----------------
    wk = wb.create_sheet("Кошница")
    wk["A1"] = "Колко струва кошницата във всяка верига"
    wk["A1"].font = Font(name=SHRIFT, bold=True, size=14, color="1F4E78")
    wk["A2"] = ("Сумата е само за продуктите, които веригата има (виж колоната „Намерени“). "
                "Верига с по-малко намерени продукти изглежда по-евтина, защото липсващите не са сметнати.")
    wk["A2"].font = Font(name=SHRIFT, size=9, color="595959")
    zaglavie_red(wk, 4, ["Верига", "Сума за кошницата", "Намерени продукти", "От общо", "Средно спрямо най-ниската"], [20, 18, 18, 10, 24])
    n = len(produkti)
    for j, v in enumerate(verigi_koloni):
        r = 5 + j
        kol = L(pv + j)
        rng = f"Сравнение!{kol}{H + 1}:{kol}{posleden}"
        kol_q = f"Сравнение!$C${H + 1}:$C${posleden}"
        kol_min = f"Сравнение!${L(km)}${H + 1}:${L(km)}${posleden}"
        wk.cell(row=r, column=1, value=v).font = Font(name=SHRIFT, bold=True)
        wk.cell(row=r, column=2, value=f"=SUMPRODUCT({kol_q},{rng})").number_format = EVRO
        wk.cell(row=r, column=3, value=f"=COUNT({rng})")
        wk.cell(row=r, column=4, value=n)
        wk.cell(row=r, column=5, value=(
            f'=IF(C{r}=0,"",SUMPRODUCT({kol_q},{rng})/SUMPRODUCT({kol_q},{kol_min},--({rng}<>""))-1)'
        )).number_format = '+0.0%;-0.0%;0.0%'
        for col in range(1, 6):
            wk.cell(row=r, column=col).border = RAMKA
    wk.cell(row=6 + len(verigi_koloni), column=1,
            value="„Средно спрямо най-ниската“: с колко % веригата е по-скъпа от най-ниската цена за същите продукти.").font = Font(name=SHRIFT, size=9, color="595959")

    # ---------------- Детайли ----------------
    wd = wb.create_sheet("Детайли")
    zaglavie_red(wd, 1, ["Продукт", "Верига", "Артикул", "Цена €", "Редовна цена €", "Промоция", "Разфасовка",
                         "€ за мярка", "Мярка", "Магазини", "Източник"], [18, 14, 48, 10, 13, 10, 16, 11, 7, 10, 12])
    r = 2
    for p in produkti:
        for v, spisak in rezultati[p.ime]["__vsichki__"].items():
            for a in spisak[:5]:
                stoinosti = [p.ime, v, a.ime, a.cena, a.redovna, "да" if a.promo else "", a.razfasovka,
                             round(a.cena_merka, 2) if a.cena_merka is not None else None, p.merka,
                             a.magazini or None, a.iztochnik]
                for col, s in enumerate(stoinosti, 1):
                    c = wd.cell(row=r, column=col, value=s)
                    if col in (4, 5, 8):
                        c.number_format = EVRO
                r += 1
    wd.auto_filter.ref = f"A1:K{max(r - 1, 1)}"
    wd.freeze_panes = "A2"

    # ---------------- Kaufland оферти ----------------
    wf = wb.create_sheet("Kaufland оферти")
    zaglavie_red(wf, 1, ["Раздел", "Продукт", "Описание", "Разфасовка", "Цена €", "Стара цена €", "Отстъпка", "Период"],
                 [26, 28, 40, 16, 10, 12, 10, 24])
    for i, o in enumerate(kaufland, 2):
        for col, s in enumerate([o.sekcia, o.zaglavie, o.podzaglavie, o.razfasovka, o.cena, o.stara, o.otstapka, o.period], 1):
            c = wf.cell(row=i, column=col, value=s)
            if col in (5, 6):
                c.number_format = EVRO
    wf.auto_filter.ref = f"A1:H{max(len(kaufland) + 1, 1)}"
    wf.freeze_panes = "A2"

    # ---------------- Информация ----------------
    wi = wb.create_sheet("Информация")
    wi.column_dimensions["A"].width = 110
    redove = [
        ("Как работи таблицата", True),
        ("Таблицата се обновява автоматично всеки ден от GitHub (ceni/obnovi.py).", False),
        ("", False),
        ("Източници", True),
        (f"• КЗП „Колко струва“ – отворени данни, ден {data_kzp}: {KZP_OPENDATA}", False),
        ("  Веригите са длъжни да подават цените си всеки ден по магазини. Взима се най-често срещаната цена", False),
        ("  в избрания град (или в цялата страна, ако няма избран град).", False),
        (f"• Kaufland – текущи оферти: {KAUFLAND_URL}", False),
        ("  Kaufland не подава данни към КЗП, затова виждаш само неговите промоции, не редовните цени.", False),
        ("", False),
        ("Как да си оправиш списъка", True),
        ("Продуктите са във файла ceni/spisak.csv в GitHub. Можеш да добавяш, махаш и сменяш редове", False),
        ("(или просто ми пиши какво да променя). Колоните:", False),
        ("• Категории КЗП – номер на групата от голямата потребителска кошница (виж „Категории“ по-долу).", False),
        ("• Думи (по желание) – ако искаш конкретна марка/вид, напр. „верея“. Търсят се цели думи в името на продукта.", False),
        ("  „а б“ = и двете думи; „а|б“ = която и да е от двете; „домат*“ = дума, която започва с „домат“.", False),
        ("• Думи за Kaufland – по тях се търси в офертите на Kaufland.", False),
        ("• Без думи – изключва продукти, които съдържат тези думи.", False),
        ("• Количество и Мярка – колко купуваш обикновено и в какво (кг, л или бр).", False),
        ("", False),
        ("Важно", True),
        ("• Сравнява се цена за кг/литър/брой. При продукти на тегло (месо, плодове, зеленчуци) цената е за кг.", False),
        ("• Когато грамажът не е написан в името (често в Lidl), продуктът се вижда в „Детайли“, но не участва", False),
        ("  в сравнението, за да не се сравняват различни разфасовки.", False),
        ("• Цената на рафта може да се различава от подадената към КЗП. Проверявай касовата бележка.", False),
        ("• Задръж мишката (или натисни) върху цена в „Сравнение“, за да видиш точния артикул.", False),
    ]
    if magazini:
        redove += [("", False), ("Магазини с данни (за избрания град)", True)]
        for v in verigi_koloni:
            if v != "Kaufland":
                redove.append((f"• {v}: {magazini.get(v, 0)} обекта", False))
    if greshki:
        redove += [("", False), ("Проблеми при последното обновяване", True)] + [(f"• {g}", False) for g in greshki]
    for i, (t, bold) in enumerate(redove, 1):
        c = wi.cell(row=i, column=1, value=t)
        c.font = Font(name=SHRIFT, bold=bold, size=12 if bold else 10, color="1F4E78" if bold else None)

    for sheet in wb.worksheets:
        obshti_stilove(sheet)
    wb.save(IZHOD)


# --------------------------------------------------------------------------- #
def main() -> int:
    produkti = zaredi_spisak()
    nastr = zaredi_nastroiki()
    grad = nastr.get("grad", "")
    osnovni = list(nastr.get("osnovni_verigi", []))
    drugi = list(nastr.get("drugi_verigi", []))
    verigi_koloni = osnovni + [v for v in drugi if v not in osnovni]
    kategorii = None         # всички категории – трябват за търсенето в приложението

    sesia = requests.Session()
    sesia.headers.update(HEADERS)
    greshki: list[str] = []

    print("Изтеглям данни от КЗП…")
    data_kzp, arhiv = kzp_arhiv(sesia)
    print(f"  архив за {data_kzp}, {len(arhiv) / 1e6:.1f} MB")
    artikuli, magazini = kzp_artikuli(arhiv, kategorii, grad, nastr.get("ekatte", ""))
    print(f"  вериги с данни: {len(artikuli)}")

    print("Изтеглям оферти от Kaufland…")
    try:
        kaufland = kaufland_oferti(sesia)
        print(f"  оферти: {len(kaufland)}")
    except Exception as e:  # сайтът може да е недостъпен – таблицата пак се прави
        kaufland = []
        greshki.append(f"Kaufland: {e}")
        print(f"  НЕУСПЕХ: {e}", file=sys.stderr)

    avto = set()
    for p in produkti:
        if not p.kategorii:
            avto.add(p.ime)
            p.kategorii = avto_kategorii(p, artikuli)
            if not p.dumi_kaufland:
                p.dumi_kaufland = p.dumi
            print(f"  „{p.ime}“: категории по думите → {sorted(p.kategorii) or 'няма съвпадения'}")

    rezultati: dict[str, dict] = {}
    for p in produkti:
        vsichki: dict[str, list[Artikul]] = {}
        for v, spisak in artikuli.items():
            k = kandidati(p, spisak)
            if k:
                vsichki[v] = k
        kk = kandidati_kaufland(p, kaufland)
        if kk:
            vsichki["Kaufland"] = kk
        proveri_za_greshki(vsichki)
        red: dict = {"__vsichki__": {}}
        for v in verigi_koloni:
            if v in vsichki:
                red[v] = vsichki[v][0]
                red["__vsichki__"][v] = vsichki[v]
        # най-евтино в останалите вериги
        drugi_kand = [k[0] for v, k in vsichki.items() if v not in verigi_koloni and k[0].cena_merka is not None]
        if drugi_kand:
            nai = min(drugi_kand, key=lambda a: a.cena_merka)
            red["__drugi__"] = nai
            red["__vsichki__"][nai.veriga_a] = vsichki[nai.veriga_a]
        rezultati[p.ime] = red

    # кратко резюме за продуктите, търсени само по думи (ползва се в отговора на формуляра)
    rezyume = []
    for p in produkti:
        if p.ime not in avto:
            continue
        nameren = [v for v in verigi_koloni + ["__drugi__"] if rezultati[p.ime].get(v)]
        if not nameren:
            rezyume.append(f"⚠️ „{p.ime}“: не намерих нищо. Пробвай с други думи (напр. само основната дума, без марка).")
            continue
        chasti = []
        for v in nameren:
            a = rezultati[p.ime][v]
            ime_v = a.veriga_a if v == "__drugi__" else v
            cena = f"{a.cena_merka:.2f} €/{p.merka}" if a.cena_merka is not None else f"{a.cena:.2f} €"
            chasti.append(f"{ime_v}: {cena} ({a.ime})")
        belezhka = "" if p.kategorii else " Няма го в данните на КЗП, затова е само от офертите на Kaufland."
        rezyume.append(f"„{p.ime}“ – " + "; ".join(chasti) + "." + belezhka)
    (PAPKA / ".rezultat.md").write_text("\n".join(f"- {r}" for r in rezyume), encoding="utf-8")

    napravi_excel(produkti, rezultati, verigi_koloni, kaufland, data_kzp, grad, magazini, greshki)
    izvadi_json(produkti, rezultati, verigi_koloni, artikuli, kaufland, data_kzp, grad, magazini)
    print(f"Готово: {IZHOD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
