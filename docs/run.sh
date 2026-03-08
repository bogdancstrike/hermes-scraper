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
  "euronews.ro"
  "adevarul.ro"
  "stirileprotv.ro"
  "hotnews.ro"
  "antena3.ro"
  # "digi24.ro"
  # "mediafax.ro"
  # "romania.europalibera.org"
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
