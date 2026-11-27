# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split()[:2])
    s = s.replace('c', 'e')
    s = s[:7].ljust(7, '.')
    s = ''.join(dict.fromkeys(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s[:5].ljust(5, '.')
    w = s.split()
    return max(w, key=len) if w else ''
