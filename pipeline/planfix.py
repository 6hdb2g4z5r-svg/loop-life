"""One daily plan for every surface: applies the locked week plan to dash.json's "plan" (strain band, day type),
keeping the health-signal cap. Usage (in the work dir): python3 planfix.py dash.json"""
import json, os, subprocess, sys
import notify as N

HERE = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[1]
D = json.load(open(path)); T = D.get('today'); P = D.get('plan')
if not P or T not in D.get('days', {}):
    sys.exit(0)
docs = lambda n: ((N.rx_get(n) or {}).get('docs') or {})
prof = docs('db_settings').get('profile') or {}
plans = [dict(v, id=k) for k, v in docs('db_weekplan').items() if isinstance(v, dict) and v.get('days')]
json.dump({'D': {'order': D['order'], 'days': D['days']}, 'prof': prof, 'T': T, 'plans': plans}, open('pf_in.json', 'w'))
js = "const f=require(process.argv[1]),a=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));process.stdout.write(JSON.stringify(f.withWeek(a.D,a.prof,a.T,a.plans)))"
r = subprocess.run(['node', '-e', js, os.path.join(HERE, 'scripts', 'dayplan.js'), 'pf_in.json'], capture_output=True, text=True, timeout=30)
os.unlink('pf_in.json')
if r.returncode or not r.stdout:
    print('planfix: kept the computed plan', r.stderr[:160]); sys.exit(0)
dp = json.loads(r.stdout); lo, hi = dp['band']
il = P.get('ill') or 0
if il >= 1:
    hi = min(hi, 10 if il == 1 else 7); lo = min(lo, hi - 3)
P.update(strain=[round(max(0, lo), 1), round(hi, 1)], type=dp['type'], day=T)
json.dump(D, open(path, 'w'), separators=(',', ':'))
print('plan', T, dp['type'], P['strain'])
