#!/usr/bin/env bash
# Loop Life refresh, GitHub Actions version.
# Wraps the unchanged pipeline scripts (pipeline/scripts/*.py, dayplan.js):
#   receiver template + inbox -> refresh.py -> dash.json -> receiver "dash" -> Telegram cards.
# Needs env: RECEIVER_URL RECEIVER_KEY TG_TOKEN TG_CHAT (GitHub Actions secrets).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
W="${RUNNER_TEMP:-/tmp}/looplife"
rm -rf "$W" && mkdir -p "$W/scripts"
cp "$HERE"/scripts/*.py "$HERE"/scripts/*.js "$W/scripts/"
cd "$W"
umask 077
printf '%s\n%s\n' "$RECEIVER_URL" "$RECEIVER_KEY" > receiver.txt
printf '%s\n%s\n' "$TG_TOKEN" "$TG_CHAT" > tg.txt

rx() { curl -sSL --max-time 120 "$RECEIVER_URL?key=$RECEIVER_KEY&$1"; }
post() {   # retry until the receiver confirms "stored" (it sometimes answers a POST like a GET)
  local r=""; for i in 1 2 3 4 5; do r="$(curl -sSL --max-time 300 -H 'Content-Type: text/plain' --data-binary "@$2" "$RECEIVER_URL?key=$RECEIVER_KEY&store=$1")"; echo "$r" | grep -q '"stored"' && break; sleep $((i*5)); done; echo "$r"; }

# 1. page template (kept on the receiver; refreshed whenever the dashboard design changes)
for i in 1 2 3 4 5; do rx 'action=state&name=template' > template.html; grep -q '/\*DATA\*/' template.html && break; sleep 15; done
[ "$(grep -c '/\*DATA\*/' template.html)" = 1 ] || { echo "template missing on receiver"; exit 1; }

# 2. previous dashboard (for Telegram "what changed" detection)
rx 'action=state&name=dash' > prev_dash.json || true
python3 - <<'PY'
import json
t = open('template.html').read()
try:
    d = open('prev_dash.json').read(); json.loads(d)
    if '"ok":false' in d.replace(' ', '')[:40]: raise ValueError
except Exception:
    d = None
open('prev.html', 'w').write(t.replace('/*DATA*/', d) if d else '')
PY

# 3. refresh (unchanged script)
out="$(python3 -I scripts/refresh.py "$W" 2>&1 || { sleep 30; python3 -I scripts/refresh.py "$W" 2>&1; })"
echo "$out" | tail -12
n="$(echo "$out" | sed -n 's/^inbox files: \([0-9]*\).*/\1/p' | head -1)"
echo "$out" | grep -q '^OK rows added' || { echo "refresh failed"; exit 1; }

# 4. publish the new dashboard data to the receiver (the iPhone app reads "dash")
#    Also re-publish when the receiver's copy lags behind the data we hold (a previous run's POST was lost in a
#    receiver outage after the inbox had already been consumed): compare the "sync" stamps of both copies.
need=0
if [ "${n:-0}" != 0 ] || [ ! -s prev.html ]; then need=1; else
  need="$(python3 - <<'PY'
import json
try:
    a = json.load(open('prev_dash.json')).get('sync') or {}
    b = json.load(open('dash.json')).get('sync') or {}
    keys = ('hr_any', 'watch_hr', 'steps', 'sleep', 'workout', 'gband')
    print(1 if any(str(a.get(k) or '') < str(b.get(k) or '') for k in keys) else 0)
except Exception:
    print(1)
PY
)"
fi
if [ "$need" = 1 ]; then
  r="$(post dash dash.json)"; echo "dash stored: ${r:0:200}"
  echo "$r" | grep -q '"stored"' || { echo "dash NOT stored on the receiver (it will be re-published next run)"; DASH_FAIL=1; }
fi

# 5. Notifications (iPhone push once subscribed, else Telegram)
python3 "$HERE/notify.py" --ensure-vapid || true
python3 - <<'PY'
import json, subprocess, os, datetime as dt
U, K = open('receiver.txt').read().split()
def blob(name):
    try:
        r = subprocess.run(['curl', '-sSL', '--max-time', '60', f'{U}?key={K}&action=state&name={name}'], capture_output=True, text=True).stdout
        j = json.loads(r); return j.get('docs', {}) if isinstance(j, dict) else {}
    except Exception:
        return {}
today = dt.datetime.now(dt.timezone.utc).date().isoformat()
json.dump({'rec': blob('db_recai').get(today) or {}, 'prof': blob('db_settings').get('profile') or {}}, open('plan.json', 'w'))
PY
if [ "${n:-0}" = 0 ]; then
  [ -s prev.html ] && python3 "$HERE/notify.py" tg_notify.py prev.html - tg.txt --empty || true
elif [ -s prev.html ]; then
  python3 "$HERE/notify.py" tg_notify.py prev.html dash.json tg.txt plan.json || echo "telegram step failed"
fi
python3 "$HERE/coach.py" dash.json || echo "coach step failed"
# backups of the hand-entered collections (meals, weight, daily log, settings, plans): kept as bak_db_<name>,
# refreshed only when the live copy did not suddenly shrink, so a receiver glitch can never overwrite a good backup
for c in meals body daily settings weekplan bike muscles; do
  rx "action=state&name=db_$c" > live.json || continue
  rx "action=state&name=bak_db_$c" > bak.json || true
  python3 - "$c" <<'PY' && post "bak_db_$c" live.json >/dev/null || true
import json, sys
def n(f):
    try:
        j = json.load(open(f)); return len(j['docs']) if isinstance(j.get('docs'), dict) else None
    except Exception:
        return None
live, bak = n('live.json'), n('bak.json')
ok = live is not None and (bak is None or live >= bak * 0.8 or bak < 5)
print('backup', sys.argv[1], 'live', live, 'bak', bak, 'update' if ok else 'KEEP OLD BACKUP (live copy shrank)')
sys.exit(0 if ok else 1)
PY
done
python3 -c "import json;D=json.load(open('dash.json'));t=D.get('today');x=D['days'].get(t,{});print('today',t,'rec',x.get('rec'),'sleep',x.get('sleep'),'strain',x.get('strain'))" || true
rm -f receiver.txt tg.txt
[ "${DASH_FAIL:-0}" = 0 ] || exit 1   # make a lost publish visible in the Actions list
