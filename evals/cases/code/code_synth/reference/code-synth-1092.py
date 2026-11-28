# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('b', 'e')
    s = s.lower()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.lower()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split()[:4])
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split())
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split())
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:2])
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w.capitalize() for w in s.split())
    w = s.split()
    return max(w, key=len) if w else ''
