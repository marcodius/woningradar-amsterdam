// Woningradar frontend: leest listings.json, toont kaarten, filters en sortering.
// Bewaren/verbergen wordt lokaal opgeslagen (localStorage).

const STORE_BEWAARD = "woningradar_bewaard";
const STORE_VERBORGEN = "woningradar_verborgen";
const NIEUW_DAGEN = 3; // "nieuw" = geplaatst binnen dit aantal dagen

let DATA = null;

function laadSet(key) {
  try { return new Set(JSON.parse(localStorage.getItem(key) || "[]")); }
  catch { return new Set(); }
}
function bewaarSet(key, set) {
  localStorage.setItem(key, JSON.stringify([...set]));
}

let bewaard = laadSet(STORE_BEWAARD);
let verborgen = laadSet(STORE_VERBORGEN);

const euro = (n) => (n == null ? "—" : "€ " + n.toLocaleString("nl-NL"));

function isNieuw(w) {
  if (!w.datum_geplaatst) return false;
  const d = new Date(w.datum_geplaatst);
  const dagen = (Date.now() - d.getTime()) / 86400000;
  return dagen <= NIEUW_DAGEN;
}

async function init() {
  try {
    const resp = await fetch("listings.json?t=" + Date.now());
    DATA = await resp.json();
  } catch (e) {
    document.getElementById("lijst").innerHTML =
      '<p class="leeg">Kon listings.json niet laden. Draai eerst de scraper.</p>';
    return;
  }
  vulKop();
  vulBuurten();
  koppelControls();
  initKaart();
  render();
}

let kaart = null;
let markerLaag = null;

function initKaart() {
  kaart = L.map("kaart", { scrollWheelZoom: false }).setView([52.365, 4.9], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(kaart);
  markerLaag = L.layerGroup().addTo(kaart);
}

// Kleur per TYPE: huur = blauw, koop = paars.
const TYPE_KLEUR = { huur: "#2563eb", koop: "#9333ea" };
const INDELING_KLEUR = { topmatch: "#16a34a", lage_match: "#d97706", afgewezen: "#94a3b8" };

function updateKaart(items) {
  if (!markerLaag) return;
  markerLaag.clearLayers();
  const punten = [];
  for (const w of items) {
    if (w.lat == null || w.lon == null) continue;
    const kleur = TYPE_KLEUR[w.type] || "#2563eb";
    // Topmatches groter en met dikkere rand, zodat ze opvallen.
    const isTop = w.indeling === "topmatch";
    const marker = L.circleMarker([w.lat, w.lon], {
      radius: isTop ? 12 : 9,
      color: isTop ? "#111827" : "#fff",
      weight: isTop ? 3 : 2,
      fillColor: kleur,
      fillOpacity: 0.95,
    });
    const prijs = w.type === "koop"
      ? `${euro(w.prijs)} k.k.${w.maandlast_koop ? ` (~${euro(w.maandlast_koop)}/mnd)` : ""}`
      : `${euro(w.prijs)}/mnd`;
    const foto = w.afbeelding_url
      ? `<img src="${esc(w.afbeelding_url)}" class="popup-foto" onerror="this.remove()">` : "";
    marker.bindPopup(
      `<div class="kaart-popup">` +
      foto +
      `<b><span class="pscore" style="background:${INDELING_KLEUR[w.indeling] || kleur}">${w.score ?? "?"}</span>` +
      `${esc(w.titel)}</b>` +
      `<span class="pill-tag ${w.type}">${w.type}</span><br>` +
      `${prijs} · ${esc(w.buurt || "")}<br>` +
      `<a href="${esc(w.url)}" target="_blank" rel="noopener">Bekijk advertentie ↗</a> · ` +
      `<a href="#" data-scroll="${w.id}">naar kaartje</a></div>`,
      { minWidth: 200 }
    );
    marker.addTo(markerLaag);
    marker._woningId = w.id;
    punten.push([w.lat, w.lon]);
  }
  if (punten.length) {
    kaart.fitBounds(punten, { padding: [30, 30], maxZoom: 14 });
  }

  // Klik in popup op "naar kaartje" -> scroll naar de woningkaart en markeer 'm.
  kaart.off("popupopen").on("popupopen", (e) => {
    const link = e.popup.getElement().querySelector("[data-scroll]");
    if (link) link.addEventListener("click", (ev) => {
      ev.preventDefault();
      scrollNaarKaart(link.dataset.scroll);
    });
  });
}

function scrollNaarKaart(id) {
  const el = document.querySelector(`article[data-id="${id}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("gemarkeerd");
  setTimeout(() => el.classList.remove("gemarkeerd"), 2000);
}

function vulKop() {
  const fmt = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleString("nl-NL", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  };
  document.getElementById("bijgewerkt").textContent = "Bijgewerkt: " + fmt(DATA.bijgewerkt);
  document.getElementById("volgende").textContent = "Volgende run: " + fmt(DATA.volgende_run);
  const t = DATA.tellers || {};
  document.getElementById("t-opgehaald").textContent = t.opgehaald ?? "–";
  document.getElementById("t-top").textContent = t.topmatch ?? "–";
  document.getElementById("t-laag").textContent = t.lage_match ?? "–";
  document.getElementById("t-afg").textContent = t.afgewezen ?? "–";
}

function vulBuurten() {
  const sel = document.getElementById("buurt");
  const buurten = [...new Set(DATA.woningen.map((w) => w.buurt).filter(Boolean))].sort();
  for (const b of buurten) {
    const opt = document.createElement("option");
    opt.value = b; opt.textContent = b;
    sel.appendChild(opt);
  }
}

function koppelControls() {
  ["sorteer", "type", "buurt"].forEach((id) =>
    document.getElementById(id).addEventListener("change", render));
  ["f-buiten", "f-nieuw", "f-zelfstandig", "f-bewaard", "f-verborgen"].forEach((id) =>
    document.getElementById(id).addEventListener("change", render));
  ["prijs-min", "prijs-max"].forEach((id) =>
    document.getElementById(id).addEventListener("input", render));

  // Snelknoppen: zet een maximumprijs of wis het prijsfilter.
  document.getElementById("prijs-snel").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    if (btn.dataset.wis) {
      document.getElementById("prijs-min").value = "";
      document.getElementById("prijs-max").value = "";
    } else if (btn.dataset.max) {
      document.getElementById("prijs-max").value = btn.dataset.max;
    }
    markeerSnelknoppen();
    render();
  });
}

function markeerSnelknoppen() {
  const max = document.getElementById("prijs-max").value;
  document.querySelectorAll("#prijs-snel button[data-max]").forEach((b) =>
    b.classList.toggle("actief", b.dataset.max === max));
}

function render() {
  const sorteer = document.getElementById("sorteer").value;
  const type = document.getElementById("type").value;
  const buurt = document.getElementById("buurt").value;
  const alleenBuiten = document.getElementById("f-buiten").checked;
  const alleenNieuw = document.getElementById("f-nieuw").checked;
  const verbergGereguleerd = document.getElementById("f-zelfstandig").checked;
  const alleenBewaard = document.getElementById("f-bewaard").checked;
  const toonVerborgen = document.getElementById("f-verborgen").checked;
  const prijsMin = parseInt(document.getElementById("prijs-min").value, 10);
  const prijsMax = parseInt(document.getElementById("prijs-max").value, 10);

  let items = DATA.woningen.filter((w) => {
    if (!toonVerborgen && verborgen.has(w.id)) return false;
    if (type !== "alles" && w.type !== type) return false;
    if (buurt !== "alles" && w.buurt !== buurt) return false;
    if (alleenBuiten && !w.buitenruimte) return false;
    if (alleenNieuw && !isNieuw(w)) return false;
    if (verbergGereguleerd && w.mogelijk_gereguleerd) return false;
    if (alleenBewaard && !bewaard.has(w.id)) return false;
    // Prijsfilter: woningen zonder prijs vallen weg zodra er een grens staat.
    if (!Number.isNaN(prijsMin)) { if (w.prijs == null || w.prijs < prijsMin) return false; }
    if (!Number.isNaN(prijsMax)) { if (w.prijs == null || w.prijs > prijsMax) return false; }
    return true;
  });

  if (sorteer === "nieuw") {
    items.sort((a, b) => new Date(b.datum_geplaatst || 0) - new Date(a.datum_geplaatst || 0));
  } else {
    const rang = { topmatch: 0, lage_match: 1, afgewezen: 2 };
    items.sort((a, b) => (rang[a.indeling] - rang[b.indeling]) || (b.score - a.score));
  }

  updateKaart(items);

  const lijst = document.getElementById("lijst");
  lijst.innerHTML = items.length
    ? items.map(kaartHtml).join("")
    : '<p class="leeg">Geen woningen die aan deze filters voldoen.</p>';

  lijst.querySelectorAll("[data-bewaar]").forEach((btn) =>
    btn.addEventListener("click", () => toggle(btn.dataset.bewaar, bewaard, STORE_BEWAARD)));
  lijst.querySelectorAll("[data-verberg]").forEach((btn) =>
    btn.addEventListener("click", () => toggle(btn.dataset.verberg, verborgen, STORE_VERBORGEN)));
}

function toggle(id, set, key) {
  if (set.has(id)) set.delete(id); else set.add(id);
  bewaarSet(key, set);
  render();
}

function fotoHtml(w) {
  // Echte foto indien beschikbaar; anders een statisch kaartbeeld van de
  // locatie; anders een neutrale placeholder. onerror degradeert netjes.
  if (w.afbeelding_url) {
    return `<img class="kaart-foto" loading="lazy" src="${esc(w.afbeelding_url)}" alt=""
      onerror="this.onerror=null;this.src='${statischeKaart(w)}'">`;
  }
  const sm = statischeKaart(w);
  if (sm) {
    return `<img class="kaart-foto fallback" loading="lazy" src="${sm}" alt="kaart"
      onerror="this.style.visibility='hidden'">`;
  }
  return `<div class="kaart-foto" aria-hidden="true"></div>`;
}

function statischeKaart(w) {
  if (w.lat == null || w.lon == null) return "";
  return `https://staticmap.openstreetmap.de/staticmap.php?center=${w.lat},${w.lon}` +
    `&zoom=15&size=240x180&markers=${w.lat},${w.lon},red-pushpin`;
}

function mapsLink(w) {
  if (w.lat != null && w.lon != null) {
    return `https://www.google.com/maps/search/?api=1&query=${w.lat},${w.lon}`;
  }
  const q = encodeURIComponent([w.adres, w.buurt, w.plaats].filter(Boolean).join(", "));
  return `https://www.google.com/maps/search/?api=1&query=${q}`;
}

function kaartHtml(w) {
  const isBewaard = bewaard.has(w.id);
  const isVerborgen = verborgen.has(w.id);

  const kenmerken = [];
  if (w.slaapkamers != null) kenmerken.push(`${w.slaapkamers} slaapkamer${w.slaapkamers === 1 ? "" : "s"}`);
  if (w.oppervlak_m2) kenmerken.push(`${w.oppervlak_m2} m²`);
  if (w.buitenruimte) kenmerken.push(w.buitenruimte_soort || "buitenruimte");
  if (w.parkeren) kenmerken.push("parkeren");
  if (w.energielabel) kenmerken.push("label " + w.energielabel);

  const prijsRegel = w.type === "koop"
    ? `${euro(w.prijs)} k.k.${w.maandlast_koop ? ` · ~${euro(w.maandlast_koop)}/mnd` : ""}`
    : `${euro(w.prijs)}/mnd${w.servicekosten ? ` + ${euro(w.servicekosten)} servicekosten` : ""}`;

  const redenen = (w.redenen || []).map((r) => `<li>${esc(r)}</li>`).join("");
  const waar = (w.waarschuwingen || []).map((r) => `<li>${esc(r)}</li>`).join("");
  const afwijs = (w.afwijs_redenen || []).map((r) => `<li>${esc(r)}</li>`).join("");
  const nieuwTag = isNieuw(w) ? '<span class="pill-tag">nieuw</span>' : "";
  const gereguleerdTag = w.mogelijk_gereguleerd
    ? '<span class="pill-tag gereguleerd" title="Lage prijs per m²: waarschijnlijk sociale/gereguleerde huur met inschrijving en inkomenseis">gereguleerd?</span>'
    : "";
  const ookOp = (w.ook_op && w.ook_op.length) ? `<span class="pill-tag">ook op: ${w.ook_op.join(", ")}</span>` : "";

  return `
  <article data-id="${w.id}" class="kaart ${w.indeling} type-${w.type} ${isVerborgen ? "verborgen-flag" : ""}">
    <div class="score-badge">${w.score ?? "?"}</div>
    ${fotoHtml(w)}
    <div class="body">
      <h3><a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(w.titel)}</a>
        <span class="pill-tag ${w.type}">${w.type}</span>${nieuwTag}${gereguleerdTag}${ookOp}
      </h3>
      <div class="prijs">${prijsRegel}</div>
      <div class="locatie">${esc(w.buurt || "")}${w.plaats ? ", " + esc(w.plaats) : ""} · bron: ${esc(w.bron)}</div>
      <div class="kenmerken">${kenmerken.map((k) => `<span>${esc(k)}</span>`).join("")}</div>
      ${redenen ? `<ul class="redenen">${redenen}</ul>` : ""}
      ${waar ? `<ul class="redenen waarschuwingen">${waar}</ul>` : ""}
      ${afwijs ? `<ul class="redenen afwijs">${afwijs}</ul>` : ""}
      ${w.type === "koop" && w.maandlast_aanname ? `<div class="maandlast-note">${esc(w.maandlast_aanname)}</div>` : ""}
    </div>
    <div class="acties">
      <button data-bewaar="${w.id}" class="${isBewaard ? "actief" : ""}">${isBewaard ? "★ Bewaard" : "☆ Bewaar"}</button>
      <button data-verberg="${w.id}" class="${isVerborgen ? "actief" : ""}">${isVerborgen ? "Verborgen" : "Verberg"}</button>
      <a class="maps-link" href="${mapsLink(w)}" target="_blank" rel="noopener">📍 Google Maps</a>
    </div>
  </article>`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

init();
