/* Цени – мобилно приложение (без външни зависимости, освен резервен скенер ZXing). */
"use strict";

const REZERVNO_HRANILISHTE = "pmitev85-create/ceni-app";
const ZXING_URL = "https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js";

const $ = (s) => document.querySelector(s);
let DANNI = null;           // целият ceni.json
let ARTIKULI = [];          // индекс: {v, ime, cena, cm, merka, promo, redovna, kat, kod, n}

// ------------------------------------------------------------------ помощни
const evro = (x) => (x == null ? "–" : x.toFixed(2).replace(".", ",") + " €");
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const norm = (s) => String(s || "").toLowerCase().replace(/ё/g, "е");

function hranilishte() {
  const h = location.hostname;
  if (h.endsWith(".github.io")) {
    const parva = location.pathname.split("/").filter(Boolean)[0];
    if (parva) return `${h.split(".")[0]}/${parva}`;
  }
  return REZERVNO_HRANILISHTE;
}

// Транслитерация, за да се намира „Vereya“ и като „ВЕРЕЯ“ и обратно.
const BG_LAT = { а:"a",б:"b",в:"v",г:"g",д:"d",е:"e",ж:"zh",з:"z",и:"i",й:"y",к:"k",л:"l",м:"m",н:"n",о:"o",п:"p",р:"r",с:"s",т:"t",у:"u",ф:"f",х:"h",ц:"ts",ч:"ch",ш:"sh",щ:"sht",ъ:"a",ь:"y",ю:"yu",я:"ya" };
const LAT_BG = [["sht","щ"],["zh","ж"],["ch","ч"],["sh","ш"],["ts","ц"],["yu","ю"],["ya","я"],["a","а"],["b","б"],["c","к"],["d","д"],["e","е"],["f","ф"],["g","г"],["h","х"],["i","и"],["j","дж"],["k","к"],["l","л"],["m","м"],["n","н"],["o","о"],["p","п"],["q","к"],["r","р"],["s","с"],["t","т"],["u","у"],["v","в"],["w","в"],["x","кс"],["y","й"],["z","з"]];
function kamLat(w) { return [...w].map((c) => BG_LAT[c] ?? c).join(""); }
function kamBg(w) {
  let out = "", i = 0;
  while (i < w.length) {
    const p = LAT_BG.find(([l]) => w.startsWith(l, i));
    if (p) { out += p[1]; i += p[0].length; } else { out += w[i]; i += 1; }
  }
  return out;
}
const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
function dumaRe(w) {
  const varianti = [...new Set([w, kamLat(w), kamBg(w)])].map(reEsc).join("|");
  return new RegExp(`(^|[^a-zа-я0-9])(${varianti})`);
}
function dumi(tekst) {
  return norm(tekst).split(/[^a-zа-я0-9%.,]+/).map((w) => w.replace(/^[.,]+|[.,]+$/g, "")).filter((w) => w.length >= 2);
}

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
  ARTIKULI = ix.artikuli.map((a) => ({
    v: ix.verigi[a[0]], ime: a[1], cena: a[2], cm: a[3], merka: a[4], promo: !!a[5],
    redovna: a[6], kat: a[7], kod: a[8] || "", n: norm(a[1]),
  }));
  $("#info").textContent = `${DANNI.grad} · цени към ${DANNI.data.split("-").reverse().join(".")}`;
  risuvaiSpisak();
  if ($("#tarsi").value) tarsiRisuvai();
}

// ------------------------------------------------------------------ 1. списък
function risuvaiKoshnica() {
  const sumi = {};
  let nai = 0;
  for (const p of DANNI.spisak) {
    const vsichki = Object.entries(p.ceni);
    if (p.drugi && p.drugi.cm != null) vsichki.push([p.drugi.veriga, p.drugi]);
    const ceni = vsichki.map(([, a]) => a.cm).filter((x) => x != null);
    if (ceni.length) nai += Math.min(...ceni) * p.kolichestvo;
    for (const [v, a] of Object.entries(p.ceni)) {
      if (a.cm == null) continue;
      sumi[v] ??= { s: 0, n: 0 };
      sumi[v].s += a.cm * p.kolichestvo;
      sumi[v].n += 1;
    }
  }
  const N = DANNI.spisak.length;
  const redove = Object.entries(sumi).sort((a, b) => b[1].n - a[1].n || a[1].s - b[1].s);
  $("#koshnica").innerHTML = `
    <h2>Кошницата ти (${N} продукта)</h2>
    <div class="red nai"><span>Ако купиш всичко най-евтино</span><b>${evro(nai)}</b></div>
    ${redove.map(([v, x]) => `<div class="red"><span>${esc(v)} <span class="muted small">(${x.n} от ${N})</span></span><b>${evro(x.s)}</b></div>`).join("")}
    <p class="muted small" style="margin:6px 0 0">Сумата е само за продуктите, които веригата има.</p>`;
}

function risuvaiSpisak() {
  if (!DANNI) return;
  risuvaiKoshnica();
  const f = norm($("#filtar").value);
  const html = DANNI.spisak
    .filter((p) => !f || norm(p.ime).includes(f))
    .map((p, i) => {
      const redove = Object.entries(p.ceni).map(([v, a]) => ({ v, ...a }));
      if (p.drugi) redove.push({ ...p.drugi, v: p.drugi.veriga, drug: true });
      const s = redove.filter((r) => r.cm != null).sort((a, b) => a.cm - b.cm);
      if (!s.length) {
        return `<div class="card produkt"><div class="glava"><h3>${esc(p.ime)}</h3><span class="muted">няма данни</span></div></div>`;
      }
      const best = s[0];
      return `<div class="card produkt" data-i="${i}">
        <div class="glava"><h3>${esc(p.ime)}</h3><span class="cena-golyama">${evro(best.cm)}<span class="small muted">/${esc(p.merka)}</span></span></div>
        <div class="kade">най-евтино в <b>${esc(best.v)}</b>${best.promo ? '<span class="badge">промоция</span>' : ""}</div>
        <div class="artikul">${esc(best.ime)}</div>
        <div class="verigi">${s.map((r, j) => `
          <div class="vred ${j === 0 ? "best" : ""}">
            <span class="v">${esc(r.v)}${r.drug ? ' <span class="muted small">(друга)</span>' : ""}${r.promo ? '<span class="badge">промо</span>' : ""}</span>
            <span class="c">${evro(r.cm)}/${esc(p.merka)}</span>
            <span class="a">${esc(r.ime)} · ${evro(r.cena)}${r.redovna ? ` <s>${evro(r.redovna)}</s>` : ""}</span>
          </div>`).join("")}
        </div>
      </div>`;
    })
    .join("");
  $("#spisak").innerHTML = html || '<p class="prazno">Няма такъв продукт в списъка.</p>';
}

$("#spisak").addEventListener("click", (e) => {
  const k = e.target.closest(".produkt");
  if (k) k.classList.toggle("open");
});
$("#filtar").addEventListener("input", risuvaiSpisak);

// ------------------------------------------------------------------ 2. търсене
function tarsi(tekst, { limit = 60 } = {}) {
  const w = dumi(tekst);
  if (!w.length) return [];
  const regs = w.map(dumaRe);
  const rez = ARTIKULI.filter((a) => regs.every((r) => r.test(a.n)));
  return rez
    .sort((a, b) => (a.cm == null) - (b.cm == null) || (a.cm ?? a.cena) - (b.cm ?? b.cena))
    .slice(0, limit);
}

function rezultatiHtml(spisak, { exact = false } = {}) {
  return spisak.map((a) => `
    <div class="rez ${exact ? "exact" : ""}">
      <span class="ime">${esc(a.ime)}${a.promo ? '<span class="badge">промо</span>' : ""}</span>
      <span class="c">${evro(a.cena)}</span>
      <span class="v">${esc(a.v)}${a.redovna && a.promo ? ` · <s>${evro(a.redovna)}</s>` : ""}</span>
      <span class="cm">${a.cm != null ? `${evro(a.cm)}/${esc(a.merka)}` : ""}</span>
    </div>`).join("");
}

function poMerka(rez) {
  const broi = {};
  rez.forEach((a) => a.merka && (broi[a.merka] = (broi[a.merka] || 0) + 1));
  return Object.entries(broi).sort((a, b) => b[1] - a[1])[0]?.[0] || "кг";
}

function blokRezultati(tekst, rez, imePredlog) {
  if (!tekst.trim()) return "";
  if (!rez.length) {
    return `<p class="prazno">Нищо не намерих за „${esc(tekst)}“.<br>Пробвай с по-малко или по-общи думи.</p>`;
  }
  const verigi = [...new Set(rez.map((a) => a.v))];
  return `
    <div class="card">
      <div class="row" style="align-items:center">
        <span class="muted small">${rez.length >= 60 ? "60+" : rez.length} резултата · ${verigi.length} вериги · най-евтино първо</span>
        <button class="btn secondary dobavi-btn" data-ime="${esc(imePredlog || tekst)}" data-dumi="${esc(tekst)}" data-merka="${poMerka(rez)}">+ В списъка</button>
      </div>
      ${rezultatiHtml(rez)}
    </div>`;
}

let tarsiTaimer;
function tarsiRisuvai() {
  const t = $("#tarsi").value;
  $("#tarsi-rez").innerHTML = blokRezultati(t, tarsi(t));
}
$("#tarsi").addEventListener("input", () => {
  clearTimeout(tarsiTaimer);
  tarsiTaimer = setTimeout(tarsiRisuvai, 150);
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
    // резервен скенер (ZXing) за браузъри без BarcodeDetector
    if (!window.ZXing) await zarediSkript(ZXING_URL);
    const hints = new Map();
    hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [ZXing.BarcodeFormat.EAN_13, ZXing.BarcodeFormat.EAN_8, ZXing.BarcodeFormat.UPC_A]);
    const chetec = new ZXing.BrowserMultiFormatReader(hints);
    zxingCtrl = chetec;
    await chetec.decodeFromConstraints({ video: { facingMode: "environment" } }, video, (rez) => {
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

async function pokajiBarkod(kod) {
  kod = String(kod).replace(/\D/g, "");
  if (!kod) return;
  const kutia = $("#skan-rez");
  kutia.innerHTML = `<p class="prazno">Търся ${esc(kod)}…</p>`;

  // 1) точно съвпадение по баркод в данните на веригите
  const tochni = ARTIKULI.filter((a) => a.kod && (a.kod === kod || a.kod.replace(/^0+/, "") === kod.replace(/^0+/, "")));

  // 2) име от Open Food Facts
  let off = null;
  try {
    const r = await fetch(`https://world.openfoodfacts.org/api/v2/product/${kod}.json?fields=product_name,product_name_bg,generic_name_bg,brands,quantity,image_front_small_url`);
    if (r.ok) {
      const j = await r.json();
      if (j.status === 1) off = j.product;
    }
  } catch (_) { /* без интернет към OFF – продължаваме */ }

  let ime = off?.product_name_bg || off?.product_name || off?.generic_name_bg || tochni[0]?.ime || "";
  const marka = (off?.brands || "").split(",")[0].trim();
  if (ime && marka && !norm(ime).includes(norm(marka))) ime = `${marka} ${ime}`;

  // думи за търсене: махаме числа и мерни единици; ако няма резултати, махаме думи отзад
  const STOP = new Set(["от", "за", "със", "със", "и", "в", "на", "с", "the", "and", "with", "of", "гр", "кг", "мл", "л", "г", "бр"]);
  let dumiS = dumi(ime).filter((w) => !/\d/.test(w) && !STOP.has(w)).slice(0, 4);
  let rez = [];
  while (dumiS.length) {
    rez = tarsi(dumiS.join(" "));
    if (rez.length) break;
    dumiS = dumiS.slice(0, -1);
  }
  const tekst = dumiS.join(" ");

  let html = "";
  if (off || tochni.length) {
    html += `<div class="card produkt-info">
      ${off?.image_front_small_url ? `<img src="${esc(off.image_front_small_url)}" alt="">` : ""}
      <div><h3>${esc(ime || "Неизвестен продукт")}</h3>
        <div class="muted small">${esc(kod)}${off?.quantity ? " · " + esc(off.quantity) : ""}</div></div>
    </div>`;
  } else {
    html += `<div class="card"><b>Не познах продукта (${esc(kod)}).</b>
      <p class="muted small" style="margin:4px 0 0">Няма го в базата Open Food Facts. Напиши какво е, например „олио бисер“:</p></div>`;
  }
  if (tochni.length) {
    html += `<div class="card"><b>Точно този продукт:</b>${rezultatiHtml(tochni, { exact: true })}</div>`;
  }
  html += `<input id="skan-dumi" class="search" type="search" value="${esc(tekst)}" placeholder="Думи за търсене">
           <div id="skan-spisak">${blokRezultati(tekst, rez, ime ? ime.split(" ").slice(0, 4).join(" ") : "")}</div>`;
  kutia.innerHTML = html;
  $("#skan-dumi").addEventListener("input", (e) => {
    const t = e.target.value;
    $("#skan-spisak").innerHTML = blokRezultati(t, tarsi(t), ime ? ime.split(" ").slice(0, 4).join(" ") : t);
  });
}

$("#start-skan").addEventListener("click", startSkan);
$("#spri").addEventListener("click", spriSkan);
$("#raachno").addEventListener("submit", (e) => { e.preventDefault(); pokajiBarkod($("#barkod").value); });

// ------------------------------------------------------------------ добавяне в списъка
document.addEventListener("click", (e) => {
  const b = e.target.closest(".dobavi-btn");
  if (!b) return;
  const ime = b.dataset.ime.trim();
  $("#d-ime").value = ime.charAt(0).toUpperCase() + ime.slice(1);
  $("#d-dumi").value = b.dataset.dumi.trim();
  $("#d-merka").value = b.dataset.merka || "кг";
  $("#d-kol").value = "1";
  $("#dobavi").showModal();
});

$("#dobavi").addEventListener("close", () => {
  if ($("#dobavi").returnValue !== "ok") return;
  const ime = $("#d-ime").value.trim();
  // в списъка думите се търсят като начало на дума (като тук в приложението)
  const dumiZaSpisak = dumi($("#d-dumi").value).map((w) => (w.endsWith("*") ? w : w + "*")).join(" ");
  const p = new URLSearchParams({
    template: "produkt.yml",
    title: `Продукт: ${ime}`,
    produkt: ime,
    dumi: dumiZaSpisak,
    kolichestvo: $("#d-kol").value.replace(",", "."),
    merka: $("#d-merka").value,
  });
  window.open(`https://github.com/${hranilishte()}/issues/new?${p.toString().replace(/\+/g, "%20")}`, "_blank");
});

// ------------------------------------------------------------------ навигация
document.querySelectorAll(".tabbtn").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tabbtn").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + b.dataset.tab));
    if (b.dataset.tab !== "skan") spriSkan();
    if (b.dataset.tab === "tarsi") $("#tarsi").focus();
  })
);
$("#obnovi").addEventListener("click", () => zaredi(true));

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
zaredi();
