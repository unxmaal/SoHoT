# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ' '.join(s.split()[:3])
    s = s.upper()
    s = s.lower()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(sorted(s))
    s = s.replace('c', 'r')
    s = s.swapcase()
    s = s.upper()
    s = ''.join(sorted(s))
    s = s.lower()
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:2])
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    s = ' '.join(s.split()[:2])
    s = ' '.join(w.capitalize() for w in s.split())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(s.split()[:2])
    w = s.split()
    return max(w, key=len) if w else ''
