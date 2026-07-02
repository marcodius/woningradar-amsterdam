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
  render();
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
  ["f-buiten", "f-nieuw", "f-bewaard", "f-verborgen"].forEach((id) =>
    document.getElementById(id).addEventListener("change", render));
}

function render() {
  const sorteer = document.getElementById("sorteer").value;
  const type = document.getElementById("type").value;
  const buurt = document.getElementById("buurt").value;
  const alleenBuiten = document.getElementById("f-buiten").checked;
  const alleenNieuw = document.getElementById("f-nieuw").checked;
  const alleenBewaard = document.getElementById("f-bewaard").checked;
  const toonVerborgen = document.getElementById("f-verborgen").checked;

  let items = DATA.woningen.filter((w) => {
    if (!toonVerborgen && verborgen.has(w.id)) return false;
    if (type !== "alles" && w.type !== type) return false;
    if (buurt !== "alles" && w.buurt !== buurt) return false;
    if (alleenBuiten && !w.buitenruimte) return false;
    if (alleenNieuw && !isNieuw(w)) return false;
    if (alleenBewaard && !bewaard.has(w.id)) return false;
    return true;
  });

  if (sorteer === "nieuw") {
    items.sort((a, b) => new Date(b.datum_geplaatst || 0) - new Date(a.datum_geplaatst || 0));
  } else {
    const rang = { topmatch: 0, lage_match: 1, afgewezen: 2 };
    items.sort((a, b) => (rang[a.indeling] - rang[b.indeling]) || (b.score - a.score));
  }

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
  const ookOp = (w.ook_op && w.ook_op.length) ? `<span class="pill-tag">ook op: ${w.ook_op.join(", ")}</span>` : "";

  return `
  <article class="kaart ${w.indeling} ${isVerborgen ? "verborgen-flag" : ""}">
    <div class="score-badge">${w.score ?? "?"}</div>
    <div class="body">
      <h3><a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(w.titel)}</a>
        <span class="pill-tag ${w.type}">${w.type}</span>${nieuwTag}${ookOp}
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
    </div>
  </article>`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

init();
