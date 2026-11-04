import sys, os, json, gzip, base64, subprocess, urllib.parse
W = sys.argv[1]
sys.path.insert(0, os.path.join(W, 'scripts'))
from hae2rows import convert, merge
URL, KEY = open(os.path.join(W, 'receiver.txt')).read().split()

def get(**params):
 q = urllib.parse.urlencode(dict(key=KEY, **params))
 return subprocess.run(['curl', '-sSL', '--max-time', '120', f'{URL}?{q}'], capture_output=True, check=True).stdout

def post(name, path):
 q = urllib.parse.urlencode(dict(key=KEY, store=name))
 r = subprocess.run(['curl', '-sSL', '--max-time', '300', '-H', 'Content-Type: text/plain', '--data-binary', '@' + path, f'{URL}?{q}'], capture_output=True, check=True).stdout
 return json.loads(r)
import time

def runlog(**kw):
 p2 = os.path.join(W, 'runlog.json')
 open(p2, 'w').write(json.dumps({'at': time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime()), **kw}))
 try:
  post('runlog', p2)
 except Exception as e:
  print('runlog failed', e)
runlog(stage='start')
state = json.loads(gzip.decompress(base64.b64decode(get(action='state', name='state'))))
files = json.loads(get(action='list'))['files']
# unreadable old inbox files stay on Drive but are not retried on every run (they cost minutes and forced a full save)
_bad = set(state.get('meta', {}).get('bad_inbox', []))
files = [f for f in files if f['id'] not in _bad]
print('inbox files:', len(files))
added = 0
ok_files = []
for f in files:
 payload = None
 for attempt in range(2):
  try:
   payload = json.loads(get(action='file', id=f['id']))
   break
  except Exception as e:
   err = e
   time.sleep(3)
 if payload is None:
  print('skip (kept in inbox)', f['name'], err)
  # older than 2 days: remember it as unreadable; a fresh file may just be a receiver hiccup, so it is retried
  if f['name'][4:12] < time.strftime('%Y%m%d', time.gmtime(time.time() - 2 * 86400)):
   state.setdefault('meta', {}).setdefault('bad_inbox', []).append(f['id'])
  continue
 try:
  rows, wks = convert(payload)
 except Exception as e:
  print('skip (bad payload)', f['name'], e)
  ok_files.append(f)
  continue
 ok_files.append(f)
 meta = state.get('meta', {})
 state = merge(state, rows, wks)
 added += len(rows)
 log = meta.get('log', []) + [[f['name'][4:19], len(rows), len(wks)]]
 meta['log'] = log[-30:]
 state['meta'] = meta
 print(f['name'], len(rows), 'rows', len(wks), 'workouts')
_lim = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time.time() + 900))
_n = len(state['rows'])
state['rows'] = [r for r in state['rows'] if r[2] <= _lim]
if len(state['rows']) != _n:
 print('dropped future rows:', _n - len(state['rows']))
json.dump(state, open(os.path.join(W, 'raw.json'), 'w'))
subprocess.run([sys.executable, '-I', os.path.join(W, 'scripts', 'compute.py'), os.path.join(W, 'raw.json'), os.path.join(W, 'dash.json')], check=True)
t = open(os.path.join(W, 'template.html')).read()
open(os.path.join(W, 'loop-life.html'), 'w').write(t.replace('/*DATA*/', open(os.path.join(W, 'dash.json')).read()))
if files:
 p = os.path.join(W, 'state.b64')
 open(p, 'wb').write(base64.b64encode(gzip.compress(json.dumps(state, separators=(',', ':')).encode(), 9)))
 # the inbox files are consumed ONLY once the receiver confirms the merged state is stored ("stored" in the
 # answer); otherwise their rows would be lost for good
 res = None
 for attempt in range(4):
  try:
   res = post('state', p)
   if isinstance(res, dict) and res.get('ok') and res.get('stored'):
    break
  except Exception as e:
   res = {'error': str(e)[:200]}
  time.sleep(20 * (attempt + 1))
 print('state saved:', res)
 if not (isinstance(res, dict) and res.get('ok') and res.get('stored')):
  raise SystemExit('state not stored on the receiver, inbox kept for the next run')
 for f in ok_files:
  for attempt in range(3):
   try:
    get(action='done', id=f['id'])
    break
   except Exception:
    time.sleep(10)
runlog(stage='done', files=len(files), rows=added)
print('OK rows added', added)
