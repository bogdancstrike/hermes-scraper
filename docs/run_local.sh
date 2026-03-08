#!/usr/bin/env bash

set -euo pipefail

# ==========================================================
# Resolve project paths
# ==========================================================

PROJECT_ROOT="/home/bogdan/workspace/dev/gen_scraper/llm-scraper"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP="python3 $PROJECT_ROOT/app.py"
VENV="$PROJECT_ROOT/.venv"

# ── Config ─────────────────────────────────────────────────
JOBS="${HERMES_JOBS:-8}"                  # parallel workers (CPU+RAM limited — Playwright is heavy)
MAX_PAGES="${HERMES_MAX_PAGES:-1}"        # listing pages per section
MAX_ARTICLES="${HERMES_MAX_ARTICLES:-10}" # max articles per domain
JOB_TIMEOUT="${HERMES_TIMEOUT:-300}"      # seconds per site (5 min default)

LOG_DIR="$SCRIPT_DIR/logs"
RESULTS_FILE="$SCRIPT_DIR/results.txt"

mkdir -p "$LOG_DIR"
rm -f "$RESULTS_FILE"

# ==========================================================
# Check prerequisites
# ==========================================================

if ! command -v parallel &>/dev/null; then
    echo "[ERROR] GNU Parallel not found. Install with: sudo apt install parallel"
    exit 1
fi

source "$VENV/bin/activate"

# ==========================================================
# Websites list
# ==========================================================

WEBSITES=$(cat <<'EOF'
biziday.ro
hotnews.ro
adevarul.ro
stirileprotv.ro
digi24.ro
euronews.ro
mediafax.ro
gandul.ro
romania.europalibera.org
antena3.ro
gov.ro
agerpres.ro
ziare.com
evz.ro
libertatea.ro
jurnalul.ro
realitatea.net
romaniatv.net
observatornews.ro
b1tv.ro
news.ro
cursdeguvernare.ro
economica.net
profit.ro
g4media.ro
spotmedia.ro
pressone.ro
romania-insider.com
romaniajournal.ro
stiri.tvr.ro
capital.ro
wall-street.ro
forbes.ro
bizlawyer.ro
agrointel.ro
dcnews.ro
activenews.ro
inpolitics.ro
qmagazine.ro
adevarulfinanciar.ro
monitorulcj.ro
monitorulsv.ro
ziaruldeiasi.ro
ziarulunirea.ro
ziaruldevrancea.ro
ziarulargesul.ro
ziarullumina.ro
banatulazi.ro
timisplus.ro
cluj24.ro
brasov.net
stiripesurse.ro
gds.ro
gorjeanul.ro
mesagerulneamt.ro
ziarulamprenta.ro
telegrafonline.ro
replicaonline.ro
observatorulph.ro
botosaneanul.ro
adevaruldeseara.ro
mesagerul.ro
sibiulindependent.ro
sibiu100.ro
oradesibiu.ro
transilvaniareporter.ro
gazetabt.ro
stiriagricole.ro
actualdecluj.ro
clujcapitala.ro
gazetadambovitei.ro
stiridinbanat.ro
aradon.ro
bihon.ro
debanat.ro
puterea.ro
stirilekanald.ro
kanald.ro
romanialibera.ro
curentul.info
bbc.co.uk
theguardian.com
ft.com
economist.com
reuters.com
apnews.com
cnn.com
nytimes.com
washingtonpost.com
bloomberg.com
politico.eu
politico.com
axios.com
theatlantic.com
theverge.com
wired.com
techcrunch.com
businessinsider.com
forbes.com
EOF
)

# ==========================================================
# Worker
# ==========================================================

run_scraper() {
    site="$1"
    log="$LOG_DIR/${site//\//_}.log"
    max_pages="$2"
    max_articles="$3"
    job_timeout="$4"

    if timeout "$job_timeout" python3 "$PROJECT_ROOT/app.py" \
        --website "$site" \
        --pages "$max_pages" \
        --articles "$max_articles" \
        > "$log" 2>&1; then
        status="SUCCESS"
    else
        exit_code=$?
        if [[ $exit_code -eq 124 ]]; then
            status="TIMEOUT"
        else
            status="FAILED"
        fi
    fi

    # Extract article count from log
    count=$(grep -oP 'total_articles=\K\d+' "$log" | tail -1 || echo "0")

    echo "$site | $status | articles=$count"
    echo "$site | $status | articles=$count" >> "$RESULTS_FILE"
}

export -f run_scraper
export PROJECT_ROOT LOG_DIR RESULTS_FILE

# ==========================================================
# Run in parallel
# ==========================================================

echo "Starting Hermes batch run: $(echo "$WEBSITES" | wc -l) sites | $JOBS parallel jobs"
echo "Limits: pages=$MAX_PAGES articles/site=$MAX_ARTICLES timeout=${JOB_TIMEOUT}s"
echo ""

echo "$WEBSITES" | parallel \
    -j "$JOBS" \
    --bar \
    run_scraper {} "$MAX_PAGES" "$MAX_ARTICLES" "$JOB_TIMEOUT"

# ==========================================================
# Report
# ==========================================================

TOTAL=$(wc -l < "$RESULTS_FILE")
SUCCESS=$(grep -c " SUCCESS " "$RESULTS_FILE" || true)
FAILED=$(grep -c " FAILED " "$RESULTS_FILE" || true)
TIMEOUT=$(grep -c " TIMEOUT " "$RESULTS_FILE" || true)

echo ""
echo "======================================="
echo " HERMES VALIDATION REPORT"
echo "======================================="
echo " Total sites  : $TOTAL"
echo " Succeeded    : $SUCCESS"
echo " Failed       : $FAILED"
echo " Timed out    : $TIMEOUT"
echo " Logs         : $LOG_DIR/"
echo "======================================="
echo ""
echo "--- Per-site results ---"
sort "$RESULTS_FILE"
