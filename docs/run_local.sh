#!/usr/bin/env bash

set -euo pipefail

# ==========================================================
# Resolve project paths
# ==========================================================

PROJECT_ROOT="/home/bogdan/workspace/dev/gen_scraper/llm-scraper"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP="python3 $PROJECT_ROOT/app.py"
VENV="$PROJECT_ROOT/.venv"

# number of parallel jobs
JOBS=8

LOG_DIR="$SCRIPT_DIR/logs"
RESULTS_FILE="$SCRIPT_DIR/results.txt"

mkdir -p "$LOG_DIR"
rm -f "$RESULTS_FILE"

# ==========================================================
# Activate Python environment
# ==========================================================

source "$VENV/bin/activate"

# ==========================================================
# Websites list
# ==========================================================

WEBSITES=$(cat <<EOF
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
bbc.com/news
theguardian.com
thetimes.co.uk
telegraph.co.uk
independent.co.uk
mirror.co.uk
thesun.co.uk
express.co.uk
metro.co.uk
inews.co.uk
ft.com
dailymail.co.uk
standard.co.uk
sky.com/news
itv.com/news
channel4.com/news
gbnews.com
politicshome.com
cityam.com
theweek.co.uk
spectator.co.uk
newstatesman.com
prospectmagazine.co.uk
politico.eu
economist.com
thestandard.co.uk
morningstaronline.co.uk
scotsman.com
heraldscotland.com
pressandjournal.co.uk
yorkshirepost.co.uk
manchestereveningnews.co.uk
liverpoolecho.co.uk
walesonline.co.uk
belfasttelegraph.co.uk
irishnews.com
kentonline.co.uk
getsurrey.co.uk
cambridge-news.co.uk
oxfordmail.co.uk
gazettelive.co.uk
examinerlive.co.uk
chroniclelive.co.uk
thenorthernecho.co.uk
derbytelegraph.co.uk
nottinghampost.com
bristolpost.co.uk
somersetlive.co.uk
cornwalllive.com
devonlive.com
plymouthherald.co.uk
sussexlive.co.uk
hampshirelive.news
essexlive.news
gloucestershirelive.co.uk
huffingtonpost.co.uk
ladbible.com/news
unilad.com/news
pinknews.co.uk
cnn.com
nytimes.com
washingtonpost.com
wsj.com
usatoday.com
latimes.com
chicagotribune.com
nypost.com
newsweek.com
time.com
theatlantic.com
politico.com
axios.com
vice.com
slate.com
vox.com
thehill.com
npr.org
pbs.org/news
abcnews.go.com
cbsnews.com
nbcnews.com
foxnews.com
msnbc.com
bloomberg.com
fortune.com
forbes.com
businessinsider.com
theverge.com
wired.com
techcrunch.com
reuters.com
apnews.com
propublica.org
reason.com
dailycaller.com
dailywire.com
motherjones.com
rollingstone.com/politics
marketwatch.com
investopedia.com/news
seekingalpha.com
realclearpolitics.com
mediapost.com
deadline.com
variety.com
hollywoodreporter.com
theintercept.com
lawfaremedia.org
nationalreview.com
theamericanconservative.com
rawstory.com
aljazeera.com/us
theguardian.com/us
usatodaynetwork.com
denverpost.com
seattletimes.com
houstonchronicle.com
bostonherald.com
boston.com
philly.com
detroitnews.com
freep.com
tampabay.com
orlandosentinel.com
miamiherald.com
dallasnews.com
startribune.com
sacbee.com
ocregister.com
sandiegouniontribune.com
star-telegram.com
EOF
)

# ==========================================================
# Worker
# ==========================================================

run_scraper() {
    site="$1"
    log="$LOG_DIR/${site//\//_}.log"

    echo "Running $site"

    if $APP --website "$site" > "$log" 2>&1; then
        echo "$site SUCCESS" >> "$RESULTS_FILE"
    else
        echo "$site FAILED" >> "$RESULTS_FILE"
    fi
}

export -f run_scraper
export APP LOG_DIR RESULTS_FILE

# ==========================================================
# Run in parallel
# ==========================================================

echo "$WEBSITES" | parallel -j "$JOBS" run_scraper {}

# ==========================================================
# Report
# ==========================================================

TOTAL=$(wc -l < "$RESULTS_FILE")
SUCCESS=$(grep -c "SUCCESS" "$RESULTS_FILE" || true)
FAILED=$(grep -c "FAILED" "$RESULTS_FILE" || true)

echo
echo "==============================="
echo "SCRAPER REPORT"
echo "==============================="
echo "Total sites : $TOTAL"
echo "Succeeded   : $SUCCESS"
echo "Failed      : $FAILED"
echo "Logs folder : $LOG_DIR"
echo "==============================="