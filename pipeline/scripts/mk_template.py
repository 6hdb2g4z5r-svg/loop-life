import sys, json
h = open(sys.argv[1], encoding='utf-8').read()
i = h.index('const D = ') + len('const D = ')
obj, end = json.JSONDecoder().raw_decode(h, i)
t = h[:i] + '/*DATA*/' + h[end:]
assert t.count('/*DATA*/') == 1 and 'function render()' in t
open(sys.argv[2], 'w', encoding='utf-8').write(t)
print('template from live page:', len(t), 'chars')
