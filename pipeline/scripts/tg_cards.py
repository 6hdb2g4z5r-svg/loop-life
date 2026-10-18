import os, json, math, subprocess, tempfile, urllib.parse
try:
 from PIL import Image, ImageDraw, ImageFont
except Exception:
 Image = None
BG = (12, 17, 23)
CARD = (27, 35, 45)
CARD2 = (34, 43, 54)
FG = (238, 242, 246)
MUTE = (142, 154, 168)
DIM = (93, 104, 118)
TRACK = (42, 51, 62)
GREEN = (47, 220, 93)
YELLOW = (243, 210, 60)
RED = (255, 77, 94)
BLUE = (43, 151, 245)
SLEEPC = (134, 174, 211)
TEAL = (127, 224, 200)
ORANGE = (255, 154, 60)
VIOLET = (125, 108, 242)
ZC = [(58, 70, 84), (95, 180, 255), (63, 208, 182), (243, 210, 60), (255, 154, 60), (255, 77, 94)]
STAGE = {'awake': (233, 238, 243), 'rem': (125, 108, 242), 'light': (134, 174, 211), 'deep': (43, 90, 170)}
LINK = 'https://claude.ai/artifact/WAZfHBEvYHs7S6dLypdek7'
W = 1080
_FONTS = {}

def F(size, weight='bold'):
 k = (size, weight)
 if k in _FONTS:
  return _FONTS[k]
 names = {'bold': ['/usr/share/fonts/opentype/inter/InterDisplay-Bold.otf', '/usr/share/fonts/opentype/inter/Inter-Bold.otf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'], 'semi': ['/usr/share/fonts/opentype/inter/InterDisplay-SemiBold.otf', '/usr/share/fonts/opentype/inter/Inter-SemiBold.otf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'], 'reg': ['/usr/share/fonts/opentype/inter/Inter-Regular.otf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'], 'med': ['/usr/share/fonts/opentype/inter/Inter-Medium.otf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']}[weight]
 f = None
 for n in names:
  if os.path.exists(n):
   try:
    f = ImageFont.truetype(n, size)
    break
   except Exception:
    pass
 if f is None:
  try:
   f = ImageFont.load_default(size)
  except Exception:
   f = ImageFont.load_default()
 _FONTS[k] = f
 return f

def rec_color(r):
 return DIM if r is None else GREEN if r >= 67 else YELLOW if r >= 34 else RED

def hm(m):
 m = round(m or 0)
 return f'{m // 60}h{m % 60:02d}'

def fmt(n, d=0):
 if n is None:
  return '–'
 s = f'{n:,.{d}f}'.replace(',', ' ')
 return s.replace('.', ',') if d else s

class Card:

 def __init__(self, h):
  self.img = Image.new('RGB', (W, h), BG)
  self.d = ImageDraw.Draw(self.img)
  self.h = h

 def text(self, xy, s, size, color=FG, weight='bold', anchor='la', spacing=0):
  f = F(size, weight)
  if spacing:
   x, y = xy
   total = sum((self.d.textlength(c, font=f) + spacing for c in s)) - spacing
   if anchor[0] == 'm':
    x -= total / 2
   elif anchor[0] == 'r':
    x -= total
   for c in s:
    self.d.text((x, y), c, font=f, fill=color, anchor='l' + anchor[1])
    x += self.d.textlength(c, font=f) + spacing
   return
  self.d.text(xy, s, font=f, fill=color, anchor=anchor)

 def wrap(self, xy, s, size, color=FG, weight='reg', width=W - 120, lh=1.35, maxlines=6):
  f = F(size, weight)
  x, y = xy
  line = ''
  n = 0
  for word in s.split():
   t = (line + ' ' + word).strip()
   if self.d.textlength(t, font=f) <= width:
    line = t
    continue
   self.d.text((x, y), line, font=f, fill=color)
   y += size * lh
   n += 1
   line = word
   if n >= maxlines - 1:
    break
  if line and n < maxlines:
   self.d.text((x, y), line, font=f, fill=color)
   y += size * lh
  return y

 def header(self, title, sub):
  self.text((60, 70), 'LOOP LIFE', 26, MUTE, 'semi', spacing=6)
  self.text((W - 60, 70), sub, 26, MUTE, 'semi', anchor='ra')
  self.text((60, 112), title, 52, FG, 'bold')

 def ring(self, cx, cy, r, w, frac, color, big, unit='', label='', sub=''):
  box = [cx - r, cy - r, cx + r, cy + r]
  self.d.arc(box, 0, 360, fill=TRACK, width=w)
  frac = max(0.0, min(1.0, frac or 0))
  if frac > 0:
   self.d.arc(box, -90, -90 + 360 * frac, fill=color, width=w)
   for ang in (-90, -90 + 360 * frac):
    a = math.radians(ang)
    px, py = (cx + (r - w / 2) * math.cos(a), cy + (r - w / 2) * math.sin(a))
    self.d.ellipse([px - w / 2, py - w / 2, px + w / 2, py + w / 2], fill=color)
  bf = F(150, 'bold')
  uf = F(64, 'bold')
  bw = self.d.textlength(big, font=bf)
  uw = self.d.textlength(unit, font=uf) if unit else 0
  x0 = cx - (bw + uw + (8 if unit else 0)) / 2
  self.d.text((x0, cy - 20), big, font=bf, fill=FG, anchor='ls' if False else 'lm')
  if unit:
   self.d.text((x0 + bw + 8, cy - 48), unit, font=uf, fill=FG, anchor='lm')
  if label:
   self.text((cx, cy + 82), label, 30, MUTE, 'semi', anchor='mm', spacing=5)
  if sub:
   self.text((cx, cy + 126), sub, 30, color, 'semi', anchor='mm')

 def tiles(self, y, items, h=170):
  n = len(items)
  gap = 20
  w = (W - 120 - gap * (n - 1)) / n
  for i, it in enumerate(items):
   lab, val, sub = (it[0], it[1], it[2] if len(it) > 2 else '')
   col = it[3] if len(it) > 3 else FG
   x = 60 + i * (w + gap)
   self.d.rounded_rectangle([x, y, x + w, y + h], 26, fill=CARD)
   self.text((x + 28, y + 30), lab.upper(), 22, MUTE, 'semi', spacing=2)
   self.text((x + 28, y + 70), val, 52 if len(val) < 8 else 40, col, 'bold')
   if sub:
    self.text((x + 28, y + 132), sub, 22, MUTE, 'reg')
  return y + h

 def band(self, y, label, lo, hi, val, mx=21, color=BLUE):
  x0, x1 = (60, W - 60)
  self.text((x0, y), label.upper(), 22, MUTE, 'semi', spacing=2)
  self.text((x1, y), f'{fmt(lo, 1)} – {fmt(hi, 1)}', 30, FG, 'bold', anchor='ra')
  yb = y + 50
  self.d.rounded_rectangle([x0, yb, x1, yb + 16], 8, fill=TRACK)
  a, b = (x0 + (x1 - x0) * lo / mx, x0 + (x1 - x0) * hi / mx)
  self.d.rounded_rectangle([a, yb, b, yb + 16], 8, fill=(color[0] // 2 + 10, color[1] // 2 + 20, color[2] // 2 + 40))
  if val is not None:
   v = x0 + (x1 - x0) * min(mx, val) / mx
   self.d.rounded_rectangle([v - 4, yb - 10, v + 4, yb + 26], 3, fill=FG)
  return yb + 40

 def zones(self, y, z, label='ZONES CARDIAQUES'):
  tot = sum(z[1:]) or 1
  self.text((60, y), label, 22, MUTE, 'semi', spacing=2)
  y += 44
  x = 60
  wd = W - 120
  for i in range(1, 6):
   seg = wd * z[i] / tot
   if seg > 0:
    self.d.rectangle([x, y, x + seg, y + 22], fill=ZC[i])
    x += seg
  y += 40
  cw = (W - 120) / 5
  for i in range(1, 6):
   self.text((60 + (i - 1) * cw, y), f'Z{i} {round(z[i])} min', 24, ZC[i], 'semi')
  return y + 40

 def hypno(self, y, hyp, start, end):
  self.text((60, y), 'PHASES', 22, MUTE, 'semi', spacing=2)
  y += 44
  rows = {'awake': 0, 'rem': 1, 'light': 2, 'deep': 3}
  rh = 26
  tot = sum((float(h[1]) for h in hyp)) or 1
  x = 60.0
  wd = W - 120
  for _, m, st in hyp:
   seg = wd * float(m) / tot
   r = rows.get(st, 2)
   self.d.rounded_rectangle([x, y + r * (rh + 8), x + max(2, seg), y + r * (rh + 8) + rh], 5, fill=STAGE.get(st, SLEEPC))
   x += seg
  yb = y + 4 * (rh + 8) + 8
  self.text((60, yb), start, 24, MUTE, 'med')
  self.text((W - 60, yb), end, 24, MUTE, 'med', anchor='ra')
  return yb + 44

 def footer(self, s):
  self.text((60, self.h - 70), s, 24, DIM, 'med')

 def save(self):
  fd, p = tempfile.mkstemp(suffix='.png')
  os.close(fd)
  self.img.save(p, 'PNG', optimize=True)
  return p

def tg_send(tgfile, caption, photo=None, dry=False):
 if dry:
  print(('[PHOTO ' + photo + '] ' if photo else '') + caption + '\n---')
  return True
 tok, chat = open(tgfile).read().split()[:2]
 if photo and len(caption) > 1000:
  head, _, rest = caption.partition('\n')
  return tg_send(tgfile, head, photo, dry) and tg_send(tgfile, rest, None, dry)
 if photo:
  args = ['curl', '-sS', '--max-time', '60', '--form-string', f'chat_id={chat}', '-F', f'photo=@{photo}', '--form-string', 'parse_mode=HTML', '--form-string', f'caption={caption}', f'https://api.telegram.org/bot{tok}/sendPhoto']
 else:
  args = ['curl', '-sS', '--max-time', '30', '-d', urllib.parse.urlencode({'chat_id': chat, 'text': caption, 'parse_mode': 'HTML', 'disable_web_page_preview': 'true'}), f'https://api.telegram.org/bot{tok}/sendMessage']
 r = subprocess.run(args, capture_output=True, text=True)
 ok = '"ok":true' in r.stdout
 if not ok and photo:
  print('photo failed:', (r.stdout or r.stderr)[:200].replace(tok, '***'))
  return tg_send(tgfile, caption, None, dry)
 print('telegram:', 'sent' if ok else 'FAILED ' + (r.stdout or r.stderr)[:200].replace(tok, '***'))
 return ok

def link(t='Ouvrir le tableau de bord'):
 return f'<a href="{LINK}">{t}</a>'

def mean(a):
 a = [x for x in a if x is not None]
 return sum(a) / len(a) if a else None

def sd(a):
 a = [x for x in a if x is not None]
 if len(a) < 2:
  return None
 m = mean(a)
 return math.sqrt(sum(((x - m) ** 2 for x in a)) / (len(a) - 1))

def strain_target(rec):
 c = 6 + (rec if rec is not None else 50) / 99 * 11
 return (round(max(0, c - 1.5), 1), round(min(21, c + 1.5), 1))

def plan_band(plan, day):
 r = (plan or {}).get('rec') or {}
 if not str(r.get('key', '')).startswith(day) or not r.get('strain'):
  return None
 import re
 m = re.search('(\\d+(?:[.,]\\d+)?)\\s*[-–]\\s*(\\d+(?:[.,]\\d+)?)', str(r['strain']))
 return (float(m.group(1).replace(',', '.')), float(m.group(2).replace(',', '.'))) if m else None

def hrv_view(D, day):
 order = D['order']
 i = order.index(day)
 ks = order[max(0, i - 59):i + 1]
 ln = [math.log(D['days'][k]['hrv']) if D['days'][k].get('hrv') else None for k in ks]
 base = [v for v in ln[:-7] if v is not None]
 m, s = (mean(base), sd(base))
 r7 = [v for v in ln[-7:] if v is not None]
 roll = mean(r7) if len(r7) >= 3 else None
 today = ln[-1]
 out = {'roll7': round(math.exp(roll), 1) if roll is not None else None, 'base': round(math.exp(m), 1) if m is not None else None, 'lo': round(math.exp(m - 0.5 * s), 1) if m is not None and s else None, 'hi': round(math.exp(m + 0.5 * s), 1) if m is not None and s else None, 'outlier': bool(today is not None and roll is not None and s and (abs(today - roll) > 2 * s))}
 out['band'] = None if roll is None or out['lo'] is None else 'below' if math.exp(roll) < out['lo'] else 'above' if math.exp(roll) > out['hi'] else 'normal'
 hv = [D['days'][k].get('hrv') for k in order[max(0, i - 30):i]]
 rh = [D['days'][k].get('rhr') for k in order[max(0, i - 30):i]]
 x = D['days'][day]
 out['hrv_high30'] = bool(x.get('hrv') and hv and all((v is None or x['hrv'] > v for v in hv)) and (len([v for v in hv if v]) >= 10))
 out['rhr_low30'] = bool(x.get('rhr') and rh and all((v is None or x['rhr'] < v for v in rh)) and (len([v for v in rh if v]) >= 10))
 rb = [v for v in rh if v]
 out['rhr_z'] = round((x['rhr'] - mean(rb)) / sd(rb), 1) if x.get('rhr') and len(rb) >= 8 and sd(rb) else None
 return out

def sleep_arch(sl):
 if not sl:
  return {}
 asleep = sl.get('asleep') or 1
 staged = (sl.get('deep') or 0) + (sl.get('rem') or 0) > 0
 hyp = sl.get('hyp') or []
 first = next((k for k, h in enumerate(hyp) if h[2] != 'awake'), None)
 last = max((k for k, h in enumerate(hyp) if h[2] != 'awake'), default=None)
 inner = hyp[first + 1:last] if first is not None and last is not None else []
 wakes = sum((1 for h in inner if h[2] == 'awake' and float(h[1]) >= 1))
 return {'deep': round(sl['deep'] / asleep * 100) if staged else None, 'rem': round(sl['rem'] / asleep * 100) if staged else None, 'eff': round(sl['asleep'] / sl['inbed'] * 100) if sl.get('inbed') else None, 'wakes': wakes, 'staged': staged}

def day_plan(D, prof, day=None):
 here = os.path.dirname(os.path.abspath(__file__))
 try:
  fd, p = tempfile.mkstemp(suffix='.json')
  os.close(fd)
  json.dump({'D': {'order': D['order'], 'days': D['days']}, 'prof': prof or {}, 'T': day}, open(p, 'w'))
  js = "const f=require(process.argv[1]),a=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));process.stdout.write(JSON.stringify(f(a.D,a.prof,a.T||undefined)))"
  r = subprocess.run(['node', '-e', js, os.path.join(here, 'dayplan.js'), p], capture_output=True, text=True, timeout=30)
  os.unlink(p)
  return json.loads(r.stdout) if r.returncode == 0 and r.stdout else None
 except Exception:
  return None
CALL_FR = {'Go hard': 'Pousse fort', 'Train': 'Entraîne-toi', 'Train light': 'Séance légère', 'Active recovery': 'Récupération active', 'Rest': 'Repos'}
DAYTYPE_FR = {'rest': 'Jour de repos', 'recovery': 'Repos actif', 'light': 'Séance légère', 'train': 'Entraînement'}

def coach_ok(rp, dp):
 if not rp or not dp:
  return bool(rp)
 c = rp.get('call', '')
 if dp['type'] in ('rest', 'recovery'):
  return c in ('Rest', 'Active recovery')
 if dp['type'] == 'light':
  return c != 'Go hard'
 return True

def today_plan(PLAN, D, day):
 dp = day_plan(D, (PLAN or {}).get('prof') or {}, day)
 rp = (PLAN or {}).get('rec') or {}
 b = plan_band(PLAN, day)
 if b and coach_ok(rp, dp):
  return (b[0], b[1], rp.get('call'), rp.get('today'), dp)
 if dp:
  return (dp['band'][0], dp['band'][1], dp['call'], dp['fr'] if dp['type'] != 'train' else None, dp)
 lo, hi = strain_target(D['days'][day].get('rec'))
 return (lo, hi, None, None, None)
