"""История на цените: редовна и платена (промо) цена за всеки артикул, по дни.

Файловете са в app/data/istoria/ – по един на месец и източник:
  kzp-ГГГГ-ММ.json     – цени от КЗП (по ден на данните)
  oferti-ГГГГ-ММ.json  – оферти от сайтовете на Kaufland и Lidl (по ден на изтеглянето)

Формат: {"nachalo": {id: стойност}, "promeni": {"ГГГГ-ММ-ДД": {id: стойност | null}}}
  стойност = [редовна]            – без промоция
           = [редовна, промо]     – на промоция (редовната може да е null)
  null     = артикулът вече го няма (за изтекли оферти)
Записват се само промените спрямо предния ден, затова файловете са малки.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PAPKA = Path(__file__).resolve().parent.parent / "app" / "data" / "istoria"


def kluch(prefiks: str, veriga: str, ime: str) -> str:
    """Кратък постоянен номер на артикул. prefiks: „k“ за КЗП, „s“ за оферта от сайт."""
    h = hashlib.sha1(f"{veriga}␟{ime}".encode("utf-8")).hexdigest()[:10]
    return prefiks + format(int(h, 16), "x")[:9]


def stoinost(redovna: float | None, platena: float) -> list:
    r = round(redovna, 2) if redovna else None
    p = round(platena, 2)
    return [r] if r == p else [r, p]


def _fail(iztochnik: str, mesec: str) -> Path:
    return PAPKA / f"{iztochnik}-{mesec}.json"


def _sastoianie(danni: dict, predi: str | None = None) -> dict:
    s = dict(danni.get("nachalo", {}))
    for den in sorted(danni.get("promeni", {})):
        if predi is not None and den >= predi:
            break
        for k, v in danni["promeni"][den].items():
            if v is None:
                s.pop(k, None)
            else:
                s[k] = v
    return s


def _zaredi_mesec(iztochnik: str, mesec: str) -> dict:
    f = _fail(iztochnik, mesec)
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    # нов месец: началото е крайното състояние от последния записан месец
    predni = sorted(p for p in PAPKA.glob(f"{iztochnik}-*.json") if p.stem.split("-", 1)[1] < mesec)
    nachalo = _sastoianie(json.loads(predni[-1].read_text(encoding="utf-8"))) if predni else {}
    return {"nachalo": nachalo, "promeni": {}}


def zapishi(iztochnik: str, den: str, zapisi: dict[str, list], mahni_lipsvashti: set[str] = frozenset(),
            imena: dict[str, list] | None = None) -> int:
    """Записва цените за деня. mahni_lipsvashti – префикси на номера (напр. „sK“), чиито
    артикули, ако днес липсват, се отбелязват като изчезнали (изтекли оферти).
    Връща броя на промените. Повторно пускане за същия ден презаписва деня."""
    PAPKA.mkdir(parents=True, exist_ok=True)
    mesec = den[:7]
    danni = _zaredi_mesec(iztochnik, mesec)
    predi = _sastoianie(danni, predi=den)
    promeni: dict = {}
    for k, v in zapisi.items():
        if predi.get(k) != v:
            promeni[k] = v
    for k in predi:
        if k not in zapisi and any(k.startswith(p) for p in mahni_lipsvashti):
            promeni[k] = None
    # ако денят е първият в месеца и няма начало – всичко отива в началото
    if not danni["nachalo"] and not danni["promeni"]:
        danni["nachalo"] = {k: v for k, v in promeni.items() if v is not None}
        danni["parvi_den"] = den
    else:
        danni["promeni"][den] = promeni
        # по-късни дни (при повторно пускане назад във времето) остават както са
    if imena:   # имената на офертите – за да се намират и след като офертата изтече
        danni.setdefault("imena", {}).update(imena)
    _fail(iztochnik, mesec).write_text(json.dumps(danni, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                                       encoding="utf-8")
    return len(promeni)


def zapisani_dni(iztochnik: str) -> set[str]:
    dni = set()
    for f in PAPKA.glob(f"{iztochnik}-*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        dni.update(d.get("promeni", {}))
        if d.get("nachalo"):
            dni.add(d.get("parvi_den", ""))
    dni.discard("")
    return dni
