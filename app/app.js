/* Цени – следене на любими продукти по веригите. Любимите се пазят на телефона. */
"use strict";

const ZXING_URL = "https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js";
const KLUCH_LYUBIMI = "ceni.lyubimi.v1";
const KLUCH_ISTORIA = "ceni.istoria.v1";

const $ = (s) => document.querySelector(s);
let DANNI = null;
let ARTIKULI = [];       // {v, ime, cena, cm, merka, promo, redovna, kat, razmer, kod, n}

// ------------------------------------------------------------------ помощни
const evro = (x) => (x == null ? "–" : x.toFixed(2).replace(".", ",") + " €");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const norm = (s) => String(s || "").toLowerCase().replace(/ё/g, "е").replace(/(\d),(\d)/g, "$1.$2");
const razmerTekst = (r, m) => (r == null ? "" : m === "кг" && r < 1 ? `${Math.round(r * 1000)} г` : m === "л" && r < 1 ? `${Math.round(r * 1000)} мл` : `${String(r).replace(".", ",")} ${m}`);
const datumBg = (iso) => iso.split("-").reverse().slice(0, 2).join(".");
const DNES = (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; })();
const predstoi = (a) => !!(a.ot && a.ot > DNES);
const izteklo = (a) => !!(a.do && a.do < DNES);
function srok(a) {
  if (predstoi(a)) return `<span class="badge skoro">от ${datumBg(a.ot)}</span>`;
  if (a.do) return `<span class="muted small"> до ${datumBg(a.do)}</span>`;
  return "";
}

function chetiLS(kluch, podrazb) {
  try { return JSON.parse(localStorage.getItem(kluch)) ?? podrazb; } catch (_) { return podrazb; }
}
function pishiLS(kluch, stoinost) {
  try { localStorage.setItem(kluch, JSON.stringify(stoinost)); } catch (_) {}
}
let LYUBIMI = chetiLS(KLUCH_LYUBIMI, []);
let ISTORIA = chetiLS(KLUCH_ISTORIA, {});

// Транслитерация: „Vereya“ намира „ВЕРЕЯ“ и обратно.
const BG_LAT = { а:"a",б:"b",в:"v",г:"g",д:"d",е:"e",ж:"zh",з:"z",и:"i",й:"y",к:"k",л:"l",м:"m",н:"n",о:"o",п:"p",р:"r",с:"s",т:"t",у:"u",ф:"f",х:"h",ц:"ts",ч:"ch",ш:"sh",щ:"sht",ъ:"a",ь:"y",ю:"yu",я:"ya" };
const LAT_BG = [["sht","щ"],["zh","ж"],["ch","ч"],["sh","ш"],["ts","ц"],["yu","ю"],["ya","я"],["a","а"],["b","б"],["c","к"],["d","д"],["e","е"],["f","ф"],["g","г"],["h","х"],["i","и"],["j","дж"],["k","к"],["l","л"],["m","м"],["n","н"],["o","о"],["p","п"],["q","к"],["r","р"],["s","с"],["t","т"],["u","у"],["v","в"],["w","в"],["x","кс"],["y","й"],["z","з"]];
const kamLat = (w) => [...w].map((c) => BG_LAT[c] ?? c).join("");
function kamBg(w) {
  let out = "", i = 0;
  while (i < w.length) {
    const p = LAT_BG.find(([l]) => w.startsWith(l, i));
    if (p) { out += p[1]; i += p[0].length; } else { out += w[i]; i += 1; }
  }
  return out;
}
const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const RE_KESH = new Map();
function dumaRe(w) {
  if (!RE_KESH.has(w)) {
    const varianti = [...new Set([w, kamLat(w), kamBg(w)])].map(reEsc).join("|");
    RE_KESH.set(w, new RegExp(`(^|[^a-zа-я0-9])(${varianti})`));
  }
  return RE_KESH.get(w);
}
function dumi(tekst) {
  return norm(tekst).split(/[^a-zа-я0-9%.]+/).map((w) => w.replace(/^\.+|\.+$/g, "")).filter((w) => w.length >= 2);
}
const saotvetstva = (a, regs) => regs.every((r) => r.test(a.n));

// ------------------------------------------------------------------ данни
async function zaredi(prinudi = false) {
  $("#info").textContent = "Зареждам цените…";
  try {
    const r = await fetch("data/ceni.json", { cache: prinudi ? "reload" : "no-cache" });
    if (!r.ok) throw new Error(r.status);
    DANNI = await r.json();
  } catch (e) {
    $("#info").textContent = "Няма връзка и няма запазени данни.";
    return;
  }
  const ix = DANNI.index;
  const p = Object.fromEntries(ix.poleta.map((x, i) => [x, i]));
  CHESTOTA = null;
  ARTIKULI = ix.artikuli.map((a) => ({
    v: ix.verigi[a[p.veriga]], ime: a[p.ime], cena: a[p.cena], cm: a[p.cena_merka], merka: a[p.merka],
    promo: !!a[p.promo], redovna: a[p.redovna], kat: a[p.kategoria], razmer: p.razmer != null ? a[p.razmer] : null,
    kod: a[p.barkod] || "", n: norm(a[p.ime]),
    ot: p.ot != null ? a[p.ot] || null : null, do: p.do != null ? a[p.do] || null : null,
  }));
  $("#info").textContent = `${DANNI.grad} · цени към ${DANNI.data.split("-").reverse().join(".")}`;
  zapishiIstoria();
  risuvaiLyubimi();
  if ($("#tarsi").value) tarsiRisuvai();
}

// ------------------------------------------------------------------ съвпадения за любим продукт
function sapostavi(f, { predstoyashti = false } = {}) {
  const regs = dumi(f.dumi).map(dumaRe);
  if (!regs.length) return [];
  const sas = ARTIKULI.filter((a) => {
    if (izteklo(a) || predstoi(a) !== predstoyashti) return false;
    if (!saotvetstva(a, regs)) return false;
    if (f.kat != null && a.kat != null && a.kat !== f.kat) return false;
    if (f.razmer != null) {
      if (a.razmer == null || a.merka !== f.merka) return false;
      if (Math.abs(a.razmer - f.razmer) / f.razmer > 0.08) return false;
    }
    return true;
  });
  // най-евтиният съвпадащ артикул във всяка верига
  const poVeriga = new Map();
  const kluchCena = (a) => (f.razmer != null ? a.cena : a.cm ?? a.cena);
  for (const a of sas) {
    const b = poVeriga.get(a.v);
    if (!b || kluchCena(a) < kluchCena(b)) poVeriga.set(a.v, a);
  }
  return [...poVeriga.values()].sort((a, b) => kluchCena(a) - kluchCena(b));
}

// Най-кратките думи, които намират продукта в най-много вериги (марка + вид обикновено).
const BOKLUK = new Set(["от", "за", "със", "и", "в", "на", "с", "the", "and", "with", "of", "гр", "г", "кг", "мл", "л", "бр",
  "вакуум", "кутия", "pet", "рет", "рп", "ок", "около", "пакет", "плик", "бутилка", "кен", "различни", "видове", "сорт", "soc", "мап"]);
let CHESTOTA = null;   // в колко артикула се среща всяка дума (рядка дума = най-вероятно марка)
function chestota(w) {
  if (!CHESTOTA) {
    CHESTOTA = new Map();
    for (const a of ARTIKULI) for (const x of new Set(dumi(a.ime))) CHESTOTA.set(x, (CHESTOTA.get(x) || 0) + 1);
  }
  return CHESTOTA.get(w) || 0;
}

// думи, които не са марка, макар да са редки
const OBSHTI = new Set(["бдс", "знп", "класик", "класически", "екстра", "extra", "premium", "премиум", "био", "bio", "light", "лайт",
  "традиционно", "традиционна", "натурално", "натурален", "домашно", "домашна", "краве", "овче", "козе", "пресен", "прясно", "свежо"]);

function marka(ime, w) {
  // Kaufland: „Марка – Описание“
  const m = ime.split(" – ");
  if (m.length > 1) {
    const parva = dumi(m[0]).filter((x) => w.includes(x));
    if (parva.length) return parva[0];
  }
  const kandidati = w.filter((x) => x.length >= 3 && !/\d/.test(x) && !OBSHTI.has(x));
  return kandidati.sort((a, b) => chestota(a) - chestota(b))[0] || null;
}

function predloziDumi(ime, { kat = null, razmer = null, merka = null } = {}) {
  const vazhna = (x) => !BOKLUK.has(x) && (/^\d+(\.\d+)?%$/.test(x) || !/\d/.test(x));
  let w = [...new Set(dumi(ime).filter(vazhna))].slice(0, 6);
  if (!w.length) return "";
  const pazi = marka(ime, w);   // марката не се маха никога
  const f = { kat, razmer, merka };
  const broi = (ws) => sapostavi({ ...f, dumi: ws.join(" ") }).length;
  let tek = broi(w);
  // На всяка стъпка: махаме дума или я съкращаваме до началото ѝ (Metro пише „НОВА БРАЗ“),
  // само ако така продуктът се намира в повече вериги. Марката не се маха, но може да се съкрати.
  let marka_ = pazi;
  for (let stapka = 0; stapka < 10; stapka++) {
    let nai = null;
    for (const x of w) {
      const hodove = [];
      if (x !== marka_ && w.length > 1) hodove.push(w.filter((y) => y !== x));
      if (x.length > 5 && !/\d/.test(x)) hodove.push(w.map((y) => (y === x ? x.slice(0, 4) : y)));
      for (const ost of hodove) {
        const b = broi(ost);
        if (!nai || b > nai.b) nai = { ost, b, x };
      }
    }
    if (!nai || nai.b <= tek) break;
    if (nai.x === marka_ && nai.ost.length === w.length) marka_ = marka_.slice(0, 4);
    w = nai.ost;
    tek = nai.b;
  }
  return w.join(" ");
}

// ------------------------------------------------------------------ история на цените
function zapishiIstoria() {
  if (!DANNI) return;
  for (const f of LYUBIMI) {
    const s = sapostavi(f);
    if (!s.length) continue;
    ISTORIA[f.id] ??= {};
    ISTORIA[f.id][DANNI.data] = Object.fromEntries(s.map((a) => [a.v, a.cena]));
    const dati = Object.keys(ISTORIA[f.id]).sort();
    for (const d of dati.slice(0, -60)) delete ISTORIA[f.id][d];   // пазим последните 60 дни
  }
  pishiLS(KLUCH_ISTORIA, ISTORIA);
}
function promyana(f, nai) {
  const ist = ISTORIA[f.id];
  if (!ist || !DANNI) return "";
  const predni = Object.keys(ist).filter((d) => d < DANNI.data).sort();
  if (!predni.length) return "";
  const d = predni[predni.length - 1];
  const stara = Math.min(...Object.values(ist[d]));
  const raz = nai - stara;
  if (Math.abs(raz) < 0.005) return `<span class="trend">= като на ${datumBg(d)}</span>`;
  return raz < 0
    ? `<span class="trend dolu">▼ ${evro(-raz)} от ${datumBg(d)}</span>`
    : `<span class="trend gore">▲ ${evro(raz)} от ${datumBg(d)}</span>`;
}

// ------------------------------------------------------------------ 1. любими
function risuvaiLyubimi() {
  if (!DANNI) return;
  const kutia = $("#lyubimi");
  if (!LYUBIMI.length) {
    $("#obobshtenie").innerHTML = "";
    kutia.innerHTML = `<div class="card prazno">
      <p style="font-size:40px;margin:0">⭐</p>
      <p><b>Още нямаш любими продукти.</b></p>
      <p>Намери продукт в <b>🔎 Търси</b> или го сканирай в <b>📷 Сканирай</b> и натисни <b>☆</b> до него.
      Ще виждаш цената му във всеки магазин.</p></div>`;
    return;
  }
  const glavni = DANNI.verigi;
  const pobedi = {};
  const html = LYUBIMI.map((f) => {
    const s = sapostavi(f);
    const merka = f.razmer != null ? null : (s[0]?.merka || f.merka);
    const cenaNa = (a) => (f.razmer != null ? a.cena : a.cm ?? a.cena);
    const lipsva = glavni.filter((v) => !s.some((a) => a.v === v));
    const skoro = sapostavi(f, { predstoyashti: true }).filter((a) => !s.length || cenaNa(a) < cenaNa(s.find((x) => x.v === a.v) || { cena: Infinity, cm: Infinity }));
    const opisanie = f.razmer != null ? razmerTekst(f.razmer, f.merka) : "всички разфасовки, цена за мярка";
    const deistvia = `<div class="deistvia"><button class="link" data-red="${f.id}">✏️ Промени</button><button class="link opasno" data-mahni="${f.id}">🗑 Махни</button></div>`;
    if (!s.length) {
      return `<div class="card produkt" data-id="${f.id}">
        <div class="glava"><h3>${esc(f.ime)}</h3><span class="muted">не е намерен</span></div>
        <div class="artikul">Днес не го намирам в нито една верига (търся „${esc(f.dumi)}“, ${esc(opisanie)}).</div>${deistvia}</div>`;
    }
    const nai = s[0];
    pobedi[nai.v] = (pobedi[nai.v] || 0) + 1;
    const edinica = merka ? `<span class="small muted">/${esc(merka)}</span>` : "";
    return `<div class="card produkt" data-id="${f.id}">
      <div class="glava"><h3>${esc(f.ime)}</h3><span class="cena-golyama">${evro(cenaNa(nai))}${edinica}</span></div>
      <div class="kade">най-евтино в <b>${esc(nai.v)}</b>${nai.promo ? '<span class="badge">промоция</span>' : ""}${srok(nai)} ${promyana(f, nai.cena)}</div>
      ${skoro.length ? `<div class="kade skoro-red">🔜 ${esc(skoro[0].v)}: ${evro(cenaNa(skoro[0]))} от ${datumBg(skoro[0].ot)}</div>` : ""}
      <div class="artikul">${esc(opisanie)} · в ${s.length} ${s.length === 1 ? "верига" : "вериги"}</div>
      <div class="verigi">${s.map((a, j) => `
        <div class="vred ${j === 0 ? "best" : ""}">
          <span class="v">${esc(a.v)}${a.promo ? '<span class="badge">промо</span>' : ""}${srok(a)}</span>
          <span class="c">${evro(cenaNa(a))}${merka ? "/" + esc(merka) : ""}</span>
          <span class="a">${esc(a.ime)} · ${evro(a.cena)}${a.promo && a.redovna ? ` <s>${evro(a.redovna)}</s>` : ""}${!merka || a.cm == null ? "" : ""}</span>
        </div>`).join("")}
        ${skoro.length ? `<div class="skoro-blok"><b>🔜 Предстоящи промоции</b>${skoro.map((a) => `
          <div class="vred"><span class="v">${esc(a.v)}</span><span class="c">${evro(cenaNa(a))}${merka ? "/" + esc(merka) : ""}</span>
          <span class="a">${esc(a.ime)} · ${evro(a.cena)} · от ${datumBg(a.ot)}${a.do ? " до " + datumBg(a.do) : ""}</span></div>`).join("")}</div>` : ""}
        ${lipsva.length ? `<p class="muted small" style="margin:6px 0 0">Няма го днес в: ${lipsva.map(esc).join(", ")}${lipsva.includes("Kaufland") ? " (за Kaufland виждам само промоциите)" : ""}</p>` : ""}
        ${deistvia}
      </div>
    </div>`;
  }).join("");
  kutia.innerHTML = html;
  const red = Object.entries(pobedi).sort((a, b) => b[1] - a[1]);
  $("#obobshtenie").innerHTML = red.length ? `<div class="card koshnica">
      <h2>Къде е най-изгодно днес</h2>
      ${red.map(([v, n], i) => `<div class="red ${i === 0 ? "nai" : ""}"><span>${esc(v)}</span><b>${n} ${n === 1 ? "любим" : "любими"}</b></div>`).join("")}
    </div>` : "";
}

$("#lyubimi").addEventListener("click", (e) => {
  const mahni = e.target.closest("[data-mahni]");
  if (mahni) {
    const f = LYUBIMI.find((x) => x.id === mahni.dataset.mahni);
    if (f && confirm(`Да махна ли „${f.ime}“ от любимите?`)) {
      LYUBIMI = LYUBIMI.filter((x) => x.id !== f.id);
      delete ISTORIA[f.id];
      pishiLS(KLUCH_LYUBIMI, LYUBIMI); pishiLS(KLUCH_ISTORIA, ISTORIA);
      risuvaiLyubimi();
    }
    return;
  }
  const red = e.target.closest("[data-red]");
  if (red) {
    const f = LYUBIMI.find((x) => x.id === red.dataset.red);
    if (f) otvoriSledi({ ...f }, true);
    return;
  }
  const k = e.target.closest(".produkt");
  if (k) k.classList.toggle("open");
});

// копие на любимите (за нов телефон или изчистен браузър)
$("#iznesi").addEventListener("click", async () => {
  const tekst = JSON.stringify({ lyubimi: LYUBIMI, istoria: ISTORIA });
  try {
    if (navigator.share) await navigator.share({ title: "Любими – копие", text: tekst });
    else { await navigator.clipboard.writeText(tekst); alert("Копието е копирано. Запази го някъде, напр. в бележка или имейл до себе си."); }
  } catch (_) { /* отказано */ }
});
$("#vnesi").addEventListener("click", () => {
  const tekst = prompt("Постави копието (текста, който си запазил):");
  if (!tekst) return;
  try {
    const d = JSON.parse(tekst);
    const novi = (d.lyubimi || []).filter((f) => !LYUBIMI.some((x) => x.id === f.id));
    LYUBIMI = LYUBIMI.concat(novi);
    ISTORIA = { ...(d.istoria || {}), ...ISTORIA };
    pishiLS(KLUCH_LYUBIMI, LYUBIMI); pishiLS(KLUCH_ISTORIA, ISTORIA);
    risuvaiLyubimi();
    alert(`Възстановени: ${novi.length} продукта.`);
  } catch (_) { alert("Това не прилича на копие от приложението."); }
});

// ------------------------------------------------------------------ диалог „Следи продукта“
let REDAKTIRAN = null;

function otvoriSledi(f, redakcia = false) {
  REDAKTIRAN = { ...f, redakcia };
  $("#s-zaglavie").textContent = redakcia ? "Промени любим продукт" : "Следи продукта";
  $("#s-ime").value = f.ime;
  $("#s-dumi").value = f.dumi;
  const imaRazmer = f.razmerPredlog != null || f.razmer != null;
  const r = f.razmer ?? f.razmerPredlog;
  $("#s-razmer-red").classList.toggle("hidden", !imaRazmer);
  $("#s-razmer").checked = f.razmer != null || (!redakcia && f.razmerPredlog != null);
  $("#s-razmer-tekst").textContent = imaRazmer ? `Само разфасовка ${razmerTekst(r, f.merka)}` : "";
  REDAKTIRAN.razmerPredlog = r;
  pregled();
  $("#sledi").showModal();
}

function tekushtLyubim() {
  return {
    id: REDAKTIRAN.id || "f" + Date.now().toString(36),
    ime: $("#s-ime").value.trim(),
    dumi: $("#s-dumi").value.trim(),
    kat: REDAKTIRAN.kat ?? null,
    merka: REDAKTIRAN.merka || "кг",
    razmer: $("#s-razmer").checked ? REDAKTIRAN.razmerPredlog : null,
  };
}

function pregled() {
  const f = tekushtLyubim();
  const s = sapostavi(f);
  $("#s-preglad").innerHTML = s.length
    ? `<b>Намира се в ${s.length} ${s.length === 1 ? "верига" : "вериги"}:</b>` +
      s.map((a) => `<div class="pred"><span>${esc(a.v)}</span><span>${evro(a.cena)}</span><span class="a">${esc(a.ime)}</span></div>`).join("")
    : `<span class="opasno">С тези думи не намирам нищо днес. Махни някоя дума или разфасовката.</span>`;
}
let pregledTaimer;
$("#s-dumi").addEventListener("input", () => { clearTimeout(pregledTaimer); pregledTaimer = setTimeout(pregled, 200); });
$("#s-razmer").addEventListener("change", pregled);

$("#sledi").addEventListener("close", () => {
  if ($("#sledi").returnValue !== "ok" || !REDAKTIRAN) return;
  const f = tekushtLyubim();
  if (!f.ime || !f.dumi) return;
  const i = LYUBIMI.findIndex((x) => x.id === f.id);
  if (i >= 0) LYUBIMI[i] = f; else LYUBIMI.push(f);
  pishiLS(KLUCH_LYUBIMI, LYUBIMI);
  zapishiIstoria();
  risuvaiLyubimi();
  pokajiSaobshtenie(`⭐ „${f.ime}“ е в любимите`);
});

function sledi(a) {
  const ime = a.ime.replace(/\s*\(.*?\)\s*$/, "")
    .replace(/(^|\s)[~+]?\d+([.,]\d+)?\s*(гр|г|кг|мл|л|бр|g|kg|ml|l)\.?(?=\s|$|,)/gi, " ")
    .replace(/\s+/g, " ").trim();
  const f = { ime: ime.charAt(0).toUpperCase() + ime.slice(1).toLowerCase(), kat: a.kat ?? null, merka: a.merka || "кг", razmerPredlog: a.razmer };
  f.dumi = predloziDumi(a.ime, { kat: f.kat, razmer: a.razmer, merka: a.merka });
  // за Kaufland няма категория – взимаме най-честата сред намерените в другите вериги
  if (f.kat == null) {
    const s = sapostavi({ ...f, razmer: null });
    const broi = {};
    s.forEach((x) => x.kat != null && (broi[x.kat] = (broi[x.kat] || 0) + 1));
    const k = Object.entries(broi).sort((x, y) => y[1] - x[1])[0];
    if (k) f.kat = Number(k[0]);
  }
  otvoriSledi(f);
}

function pokajiSaobshtenie(tekst) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; document.body.appendChild(t); }
  t.textContent = tekst;
  t.classList.add("vidim");
  setTimeout(() => t.classList.remove("vidim"), 2200);
}

// ------------------------------------------------------------------ 2. търсене
let POSLEDNI = [];   // за бутоните ☆
function tarsi(tekst, { limit = 60 } = {}) {
  const regs = dumi(tekst).map(dumaRe);
  if (!regs.length) return [];
  return ARTIKULI.filter((a) => !izteklo(a) && saotvetstva(a, regs))
    .sort((a, b) => (a.cm == null) - (b.cm == null) || (a.cm ?? a.cena) - (b.cm ?? b.cena))
    .slice(0, limit);
}

function rezultatiHtml(spisak) {
  const sledeni = new Set(LYUBIMI.flatMap((f) => sapostavi(f)));
  return spisak.map((a) => {
    const i = POSLEDNI.push(a) - 1;
    const veche = sledeni.has(a);
    return `
    <div class="rez">
      <button class="zvezda ${veche ? "pylna" : ""}" data-i="${i}" aria-label="Следи този продукт">${veche ? "★" : "☆"}</button>
      <span class="ime">${esc(a.ime)}${a.promo && !predstoi(a) ? '<span class="badge">промо</span>' : ""}${srok(a)}</span>
      <span class="c">${evro(a.cena)}</span>
      <span class="v">${esc(a.v)}${a.redovna && a.promo ? ` · <s>${evro(a.redovna)}</s>` : ""}</span>
      <span class="cm">${a.cm != null ? `${evro(a.cm)}/${esc(a.merka)}` : ""}</span>
    </div>`;
  }).join("");
}

function blokRezultati(tekst, rez) {
  if (!tekst.trim()) return '<p class="prazno">Напиши какво търсиш. Натисни ☆ до продукт, за да го следиш.</p>';
  if (!rez.length) return `<p class="prazno">Нищо не намерих за „${esc(tekst)}“.<br>Пробвай с по-малко или по-общи думи.</p>`;
  const verigi = new Set(rez.map((a) => a.v)).size;
  return `<div class="card">
      <p class="muted small" style="margin:0">${rez.length >= 60 ? "60+" : rez.length} резултата · ${verigi} вериги · най-евтино (за кг/л) първо. Натисни ☆, за да следиш.</p>
      ${rezultatiHtml(rez)}
    </div>`;
}

let tarsiTaimer;
function tarsiRisuvai() {
  POSLEDNI = [];
  const t = $("#tarsi").value;
  $("#tarsi-rez").innerHTML = blokRezultati(t, tarsi(t));
}
$("#tarsi").addEventListener("input", () => { clearTimeout(tarsiTaimer); tarsiTaimer = setTimeout(tarsiRisuvai, 150); });

document.addEventListener("click", (e) => {
  const z = e.target.closest(".zvezda");
  if (z && POSLEDNI[z.dataset.i]) sledi(POSLEDNI[z.dataset.i]);
});

// ------------------------------------------------------------------ 3. сканиране
let potok = null, aktivno = false, zxingCtrl = null;

async function startSkan() {
  $("#skan-rez").innerHTML = "";
  if (!navigator.mediaDevices?.getUserMedia) {
    $("#skan-rez").innerHTML = '<p class="prazno">Този браузър не дава достъп до камерата. Въведи баркода ръчно.</p>';
    return;
  }
  $("#kamera-kutia").classList.remove("hidden");
  $("#start-skan").classList.add("hidden");
  aktivno = true;
  const video = $("#video");
  try {
    if ("BarcodeDetector" in window) {
      const formati = await BarcodeDetector.getSupportedFormats();
      if (formati.includes("ean_13")) {
        potok = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        video.srcObject = potok;
        await video.play();
        const det = new BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e"] });
        const cikal = async () => {
          if (!aktivno) return;
          try {
            const kodove = await det.detect(video);
            if (kodove.length) return nameren(kodove[0].rawValue);
          } catch (_) { /* кадърът още не е готов */ }
          requestAnimationFrame(cikal);
        };
        return cikal();
      }
    }
    if (!window.ZXing) await zarediSkript(ZXING_URL);
    const hints = new Map();
    hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [ZXing.BarcodeFormat.EAN_13, ZXing.BarcodeFormat.EAN_8, ZXing.BarcodeFormat.UPC_A]);
    zxingCtrl = new ZXing.BrowserMultiFormatReader(hints);
    await zxingCtrl.decodeFromConstraints({ video: { facingMode: "environment" } }, video, (rez) => {
      if (rez && aktivno) nameren(rez.getText());
    });
  } catch (e) {
    spriSkan();
    $("#skan-rez").innerHTML = `<p class="prazno">Не успях да пусна камерата (${esc(e.message || e)}).<br>Разреши достъп до камерата или въведи баркода ръчно.</p>`;
  }
}

function spriSkan() {
  aktivno = false;
  potok?.getTracks().forEach((t) => t.stop());
  potok = null;
  try { zxingCtrl?.reset(); } catch (_) {}
  zxingCtrl = null;
  $("#kamera-kutia").classList.add("hidden");
  $("#start-skan").classList.remove("hidden");
}

function zarediSkript(src) {
  return new Promise((ok, greshka) => {
    const s = document.createElement("script");
    s.src = src; s.onload = ok; s.onerror = () => greshka(new Error("не се зареди скенерът"));
    document.head.appendChild(s);
  });
}

async function nameren(kod) {
  spriSkan();
  navigator.vibrate?.(80);
  $("#barkod").value = kod;
  await pokajiBarkod(kod);
}

function razmerOtKolichestvo(q) {
  const m = norm(q).match(/(\d+(?:\.\d+)?)\s*(kg|кг|g|гр|г|l|л|ml|мл)\b/);
  if (!m) return {};
  const x = parseFloat(m[1]);
  const e = m[2];
  if (["kg", "кг"].includes(e)) return { razmer: x, merka: "кг" };
  if (["g", "гр", "г"].includes(e)) return { razmer: x / 1000, merka: "кг" };
  if (["l", "л"].includes(e)) return { razmer: x, merka: "л" };
  return { razmer: x / 1000, merka: "л" };
}

async function pokajiBarkod(kod) {
  kod = String(kod).replace(/\D/g, "");
  if (!kod) return;
  const kutia = $("#skan-rez");
  kutia.innerHTML = `<p class="prazno">Търся ${esc(kod)}…</p>`;
  POSLEDNI = [];

  let off = null;
  try {
    const r = await fetch(`https://world.openfoodfacts.org/api/v2/product/${kod}.json?fields=product_name,product_name_bg,generic_name_bg,brands,quantity,image_front_small_url`);
    if (r.ok) { const j = await r.json(); if (j.status === 1) off = j.product; }
  } catch (_) { /* без връзка към Open Food Facts */ }

  let ime = off?.product_name_bg || off?.product_name || off?.generic_name_bg || "";
  const marka = (off?.brands || "").split(",")[0].trim();
  if (ime && marka && !norm(ime).includes(norm(marka))) ime = `${marka} ${ime}`;
  const { razmer, merka } = razmerOtKolichestvo(off?.quantity || "");

  let tekst = ime ? predloziDumi(ime) : "";
  let rez = tarsi(tekst);
  // ако нищо не излиза – махаме думи отзад
  let ws = tekst.split(" ").filter(Boolean);
  while (!rez.length && ws.length > 1) { ws = ws.slice(0, -1); rez = tarsi(ws.join(" ")); }
  tekst = ws.join(" ");

  let html;
  if (off) {
    html = `<div class="card produkt-info">
      ${off.image_front_small_url ? `<img src="${esc(off.image_front_small_url)}" alt="">` : ""}
      <div style="flex:1"><h3>${esc(ime)}</h3><div class="muted small">${esc(kod)}${off.quantity ? " · " + esc(off.quantity) : ""}</div></div>
      <button class="btn" id="sledi-skan">☆ Следи</button>
    </div>`;
  } else {
    html = `<div class="card"><b>Не познах продукта (${esc(kod)}).</b>
      <p class="muted small" style="margin:4px 0 0">Няма го в базата Open Food Facts. Напиши какво е (напр. „олио бисер“) и натисни ☆ до правилния артикул.</p></div>`;
  }
  html += `<input id="skan-dumi" class="search" type="search" value="${esc(tekst)}" placeholder="Думи за търсене">
           <div id="skan-spisak">${blokRezultati(tekst, rez)}</div>`;
  kutia.innerHTML = html;
  $("#skan-dumi").addEventListener("input", (e) => {
    POSLEDNI = [];
    $("#skan-spisak").innerHTML = blokRezultati(e.target.value, tarsi(e.target.value));
  });
  $("#sledi-skan")?.addEventListener("click", () => {
    const f = { ime, kat: null, merka: merka || "кг", razmerPredlog: razmer ?? null, dumi: $("#skan-dumi").value || tekst };
    const s = sapostavi({ ...f, razmer: null });
    const broi = {};
    s.forEach((x) => x.kat != null && (broi[x.kat] = (broi[x.kat] || 0) + 1));
    const k = Object.entries(broi).sort((x, y) => y[1] - x[1])[0];
    if (k) f.kat = Number(k[0]);
    otvoriSledi(f);
  });
}

$("#start-skan").addEventListener("click", startSkan);
$("#spri").addEventListener("click", spriSkan);
$("#raachno").addEventListener("submit", (e) => { e.preventDefault(); pokajiBarkod($("#barkod").value); });

// ------------------------------------------------------------------ навигация
document.querySelectorAll(".tabbtn").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tabbtn").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + b.dataset.tab));
    if (b.dataset.tab !== "skan") spriSkan();
    if (b.dataset.tab === "lyubimi") risuvaiLyubimi();
    if (b.dataset.tab === "tarsi") { tarsiRisuvai(); $("#tarsi").focus(); }
  })
);
$("#obnovi").addEventListener("click", () => zaredi(true));

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
zaredi();
