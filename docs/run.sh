#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Hermes — Scraper Run Script
# ══════════════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./docs/run.sh                  # scrape all configured websites
#   ./docs/run.sh biziday.ro       # scrape a single site
#
# Prerequisites:
#   docker compose up -d --build   # start the stack first
#
# ══════════════════════════════════════════════════════════════════════════════
# HOW TO CONFIGURE WEBSITES
# ──────────────────────────
# Edit the WEBSITES array below to add/remove domains.
# Format: "domain.ro" (no protocol, no trailing slash)
#
# HOW TO ADJUST PER-RUN PARAMETERS
# ──────────────────────────────────
# MAX_PAGES   — how many listing pages to traverse per section (default: 3)
# MAX_ARTICLES — how many articles to scrape per domain per run (default: 30)
#
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Target websites ────────────────────────────────────────────────────────────
# Add or remove entries here. One domain per line.
WEBSITES=(
  "biziday.ro"
  "hotnews.ro"
  "adevarul.ro"
  "stirileprotv.ro"
  "digi24.ro"
  "euronews.ro"
  "mediafax.ro"
  "gandul.ro"
  "romania.europalibera.org"
  "antena3.ro"
  "gov.ro"
  "agerpres.ro"
  "ziare.com"
  "evz.ro"
  "libertatea.ro"
  "jurnalul.ro"
  "realitatea.net"
  "romaniatv.net"
  "observatornews.ro"
  "b1tv.ro"
  "news.ro"
  "cursdeguvernare.ro"
  "economica.net"
  "profit.ro"
  "g4media.ro"
  "spotmedia.ro"
  "pressone.ro"
  "romania-insider.com"
  "romaniajournal.ro"
  "stiri.tvr.ro"
  "capital.ro"
  "wall-street.ro"
  "forbes.ro"
  "bizlawyer.ro"
  "agrointel.ro"
  "dcnews.ro"
  "activenews.ro"
  "inpolitics.ro"
  "qmagazine.ro"
  "adevarulfinanciar.ro"
  "monitorulcj.ro"
  "monitorulsv.ro"
  "ziaruldeiasi.ro"
  "ziarulunirea.ro"
  "ziaruldevrancea.ro"
  "ziarulargesul.ro"
  "ziarullumina.ro"
  "banatulazi.ro"
  "timisplus.ro"
  "cluj24.ro"
  "brasov.net"
  "stiripesurse.ro"
  "gds.ro"
  "gorjeanul.ro"
  "mesagerulneamt.ro"
  "ziarulamprenta.ro"
  "telegrafonline.ro"
  "replicaonline.ro"
  "observatorulph.ro"
  "botosaneanul.ro"
  "adevaruldeseara.ro"
  "mesagerul.ro"
  "sibiulindependent.ro"
  "sibiu100.ro"
  "oradesibiu.ro"
  "transilvaniareporter.ro"
  "gazetabt.ro"
  "stiriagricole.ro"
  "actualdecluj.ro"
  "clujcapitala.ro"
  "gazetadambovitei.ro"
  "stiridinbanat.ro"
  "aradon.ro"
  "bihon.ro"
  "debanat.ro"
  "puterea.ro"
  "stirilekanald.ro"
  "kanald.ro"
  "romanialibera.ro"
  "curentul.info"
  "bbc.co.uk"
  "bbc.com/news"
  "theguardian.com"
  "thetimes.co.uk"
  "telegraph.co.uk"
  "independent.co.uk"
  "mirror.co.uk"
  "thesun.co.uk"
  "express.co.uk"
  "metro.co.uk"
  "inews.co.uk"
  "ft.com"
  "dailymail.co.uk"
  "standard.co.uk"
  "sky.com/news"
  "itv.com/news"
  "channel4.com/news"
  "gbnews.com"
  "politicshome.com"
  "cityam.com"
  "theweek.co.uk"
  "spectator.co.uk"
  "newstatesman.com"
  "prospectmagazine.co.uk"
  "politico.eu"
  "economist.com"
  "thestandard.co.uk"
  "morningstaronline.co.uk"
  "scotsman.com"
  "heraldscotland.com"
  "pressandjournal.co.uk"
  "yorkshirepost.co.uk"
  "manchestereveningnews.co.uk"
  "liverpoolecho.co.uk"
  "walesonline.co.uk"
  "belfasttelegraph.co.uk"
  "irishnews.com"
  "kentonline.co.uk"
  "getsurrey.co.uk"
  "cambridge-news.co.uk"
  "oxfordmail.co.uk"
  "gazettelive.co.uk"
  "examinerlive.co.uk"
  "chroniclelive.co.uk"
  "thenorthernecho.co.uk"
  "derbytelegraph.co.uk"
  "nottinghampost.com"
  "bristolpost.co.uk"
  "somersetlive.co.uk"
  "cornwalllive.com"
  "devonlive.com"
  "plymouthherald.co.uk"
  "sussexlive.co.uk"
  "hampshirelive.news"
  "essexlive.news"
  "gloucestershirelive.co.uk"
  "huffingtonpost.co.uk"
  "ladbible.com/news"
  "unilad.com/news"
  "pinknews.co.uk"
  "cnn.com"
  "nytimes.com"
  "washingtonpost.com"
  "wsj.com"
  "usatoday.com"
  "latimes.com"
  "chicagotribune.com"
  "nypost.com"
  "newsweek.com"
  "time.com"
  "theatlantic.com"
  "politico.com"
  "axios.com"
  "vice.com"
  "slate.com"
  "vox.com"
  "thehill.com"
  "npr.org"
  "pbs.org/news"
  "abcnews.go.com"
  "cbsnews.com"
  "nbcnews.com"
  "foxnews.com"
  "msnbc.com"
  "bloomberg.com"
  "fortune.com"
  "forbes.com"
  "businessinsider.com"
  "theverge.com"
  "wired.com"
  "techcrunch.com"
  "reuters.com"
  "apnews.com"
  "propublica.org"
  "reason.com"
  "dailycaller.com"
  "dailywire.com"
  "motherjones.com"
  "rollingstone.com/politics"
  "marketwatch.com"
  "investopedia.com/news"
  "seekingalpha.com"
  "realclearpolitics.com"
  "mediapost.com"
  "deadline.com"
  "variety.com"
  "hollywoodreporter.com"
  "theintercept.com"
  "lawfaremedia.org"
  "nationalreview.com"
  "theamericanconservative.com"
  "rawstory.com"
  "aljazeera.com/us"
  "theguardian.com/us"
  "usatodaynetwork.com"
  "denverpost.com"
  "seattletimes.com"
  "houstonchronicle.com"
  "bostonherald.com"
  "boston.com"
  "philly.com"
  "detroitnews.com"
  "freep.com"
  "tampabay.com"
  "orlandosentinel.com"
  "miamiherald.com"
  "dallasnews.com"
  "startribune.com"
  "sacbee.com"
  "ocregister.com"
  "sandiegouniontribune.com"
  "star-telegram.com"
)

# ── Scraping parameters ────────────────────────────────────────────────────────
MAX_PAGES="${HERMES_MAX_PAGES:-3}"       # listing pages per section
MAX_ARTICLES="${HERMES_MAX_ARTICLES:-30}" # total articles per domain

# ── Internals ─────────────────────────────────────────────────────────────────
CONTAINER="hermes-scraper"
COMPOSE_FILE="$(dirname "$0")/../docker-compose.yml"

log()  { echo "[hermes] $*"; }
ok()   { echo "[hermes] ✓ $*"; }
err()  { echo "[hermes] ✗ $*" >&2; }

# Allow running a single domain via argument
if [[ $# -gt 0 ]]; then
  WEBSITES=("$@")
  log "Running for: ${WEBSITES[*]}"
fi

# ── Ensure the stack is running ────────────────────────────────────────────────
log "Checking Docker Compose stack..."
if ! docker compose -f "$COMPOSE_FILE" ps --services --filter status=running 2>/dev/null \
    | grep -q scraper; then
  log "Stack not running — starting it now..."
  docker compose -f "$COMPOSE_FILE" up -d --build
  log "Waiting for services to be healthy..."
  sleep 10
fi

# ── Run scraper for each website ───────────────────────────────────────────────
FAILED=()
SUCCEEDED=()

for domain in "${WEBSITES[@]}"; do
  log "━━━ Scraping: $domain (pages=$MAX_PAGES articles=$MAX_ARTICLES) ━━━"
  if docker compose -f "$COMPOSE_FILE" exec -T "$CONTAINER" \
      python app.py --website "$domain" --pages "$MAX_PAGES" --articles "$MAX_ARTICLES"; then
    ok "$domain — done"
    SUCCEEDED+=("$domain")
  else
    err "$domain — FAILED (exit code $?)"
    FAILED+=("$domain")
  fi
done

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════"
echo " Hermes run complete"
echo "══════════════════════════════════════"
echo " Succeeded : ${#SUCCEEDED[@]}  — ${SUCCEEDED[*]:-none}"
echo " Failed    : ${#FAILED[@]}  — ${FAILED[*]:-none}"
echo " Output    : ./output/"
echo "══════════════════════════════════════"

[[ ${#FAILED[@]} -eq 0 ]]   # exit 0 only if all succeeded
