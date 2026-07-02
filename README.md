# Woningradar Amsterdam

Verzamelt woningadvertenties (huur en koop), scoort ze tegen Jennifers eisen en
toont ze op een statische site. De scraper draait periodiek via GitHub Actions,
schrijft `docs/listings.json`, en de site wordt via GitHub Pages gepubliceerd.

Zelfde opzet als de vacatureradar: **ophalen → normaliseren → ontdubbelen →
scoren → tonen**, met filters erbovenop.

## Wat het doet

- Haalt woningen op per bron (modulair, per bron aan/uit te zetten).
- Normaliseert alles naar één schema (zie `woningradar/schema.py`).
- Past **harde filters** toe (budget, locatie, min. 1 slaapkamer, zelfstandig).
- Geeft een **score (1–10)** en deelt in als *topmatch*, *lage match* of *afgewezen*.
- Toont per woning een korte lijst **"Waarom deze match?"** en waarschuwingen.
- Rekent voor koopwoningen de **bruto maandlast** uit (annuïteitenhypotheek).

## Projectstructuur

```
config.yaml                 # alle criteria, scoregewichten en hypotheekrente
requirements.txt
woningradar/
  run.py                    # orchestrator (entrypoint)
  config.py                 # laadt config.yaml
  schema.py                 # Listing-schema + parse-hulpjes
  scoring.py                # harde filters + scoring + indeling
  mortgage.py               # annuïteitenberekening (koop)
  dedup.py                  # ontdubbeling
  sources/
    base.py                 # nette HTTP: rate limiting + robots.txt
    demo.py                 # lokale JSON-fixture (altijd werkend)
    huurwoningen.py         # Huurwoningen.nl (best-effort)
    pararius.py             # Pararius (standaard UIT — verbiedt scrapen)
    funda.py                # Funda (standaard UIT — verbiedt scrapen)
data/demo_listings.json     # voorbeelddata voor de demobron
docs/                       # de statische site (GitHub Pages)
  index.html  app.js  styles.css  listings.json
.github/workflows/woningradar.yml
```

## Lokaal testen

```bash
pip install -r requirements.txt
python -m woningradar.run           # schrijft docs/listings.json
```

De site bekijken:

```bash
cd docs && python -m http.server 8000
# open http://localhost:8000
```

Standaard staan alleen de **demobron** en **Huurwoningen.nl** aan, zodat de
volledige keten meteen werkt. Begin klein: krijg één of twee bronnen werkend,
voeg daarna pas meer toe.

## Op GitHub zetten

1. Maak een repo en push deze map.
2. Ga naar **Settings → Pages** en zet de bron op **GitHub Actions**.
3. Ga naar **Actions**, kies **Woningradar** en draai hem één keer handmatig
   (*Run workflow*). Daarna draait hij elke 3 uur via de cron.
4. De site verschijnt op `https://<gebruiker>.github.io/<repo>/`.

De workflow committeert `docs/listings.json` terug naar de repo en deployt de
`docs/`-map naar Pages.

## Aanpassen zonder in de code te duiken — `config.yaml`

- **Criteria:** `huur_max_kaal`, `koop_maandlast_max`, `min_slaapkamers`,
  `toegestane_plaatsen`.
- **Hypotheekrente:** `hypotheek.rente_jaarlijks` (start 4,1%). Pas dit aan als
  de rente verandert; de koop-maandlasten worden opnieuw berekend.
- **Scoregewichten:** onder `scoring.bonus` en `scoring.straf`. Elke plus/min is
  een instelbaar getal. Grenzen tussen topmatch/lage match staan onder
  `scoring.indeling`.
- **Bronnen aan/uit:** onder `bronnen`, zet `ingeschakeld: true/false`.
- **Nette omgang:** `netwerk.user_agent`, `request_delay_seconden`,
  `respecteer_robots`.

## Een bron toevoegen

1. Maak `woningradar/sources/mijnbron.py` met een klasse die erft van
   `BaseSource`, zet `naam = "mijnbron"` en implementeer `haal_op()` die een
   lijst `Listing`-objecten teruggeeft. Gebruik `self.get(url)` voor requests
   (die regelt rate limiting en de robots-check).
2. Registreer hem in `woningradar/sources/__init__.py` in `REGISTER`.
3. Voeg een blok toe onder `bronnen:` in `config.yaml` met `ingeschakeld: true`.

## Belangrijk: scrapen en de spelregels

Sommige sites — waaronder **Funda en Pararius** — verbieden scrapen in hun
voorwaarden en blokkeren bots actief. Die modules staan daarom **standaard uit**.
Gebruik waar mogelijk een officiële feed of partner-API. De radar respecteert
`robots.txt`, stelt een nette user-agent in, houdt een pauze tussen requests
(rate limiting) en vangt blokkades (403/429) netjes af: valt één bron uit, dan
blijft de rest gewoon werken.

Woningsites veranderen hun opmaak en beveiliging regelmatig, dus scrapers gaan
af en toe stuk en vragen onderhoud (meestal het bijwerken van CSS-selectors in
de betreffende module).

### JavaScript-zware bronnen (Playwright)

Voor sites die pas na JavaScript hun inhoud tonen is `requests` niet genoeg.
Installeer dan Playwright:

```bash
pip install playwright
python -m playwright install chromium
```

En haal de HTML op met een headless browser in plaats van `self.get()`. In de
GitHub Actions workflow staat een uitgecommentarieerde stap klaar om Playwright
te installeren.

## Koopberekening — aannames

De bruto maandlast wordt berekend met een annuïteitenhypotheek over de volledige
vraagprijs, tegen de rente uit `config.yaml` (start 4,1%, 30 jaar vast, NHG,
stand juli 2026), **exclusief** kosten koper. Een eventuele erfpachtcanon wordt
per maand bij de maandlast opgeteld en getoetst aan de grens van €1.500. De
gebruikte aanname staat bij elke koopwoning in de frontend. Kosten koper en de
startersvrijstelling zijn niet in de maandlast verwerkt; houd daar los rekening
mee.
