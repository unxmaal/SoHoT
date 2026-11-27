# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = ' '.join(s.split()[:3])
    s = ''.join(dict.fromkeys(s))
    s = s.replace('t', 'i')
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = s.replace('o', 'n')
    w = s.split()
    return max(w, key=len) if w else ''
