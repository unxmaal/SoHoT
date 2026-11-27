# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = ' '.join(s.split()[:4])
    s = s.replace('s', 'b')
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(reversed(s.split()))
    s = s.replace('c', 't')
    s = s.lower()
    w = s.split()
    return max(w, key=len) if w else ''
