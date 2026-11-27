# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(s):
    s = ''.join(sorted(s))
    s = s.upper()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s[:5].ljust(5, '.')
    s = ' '.join(s.split()[:2])
    s = s.upper()
    s = ' '.join(s.split())
    s = ' '.join(reversed(s.split()))
    w = s.split()
    return max(w, key=len) if w else ''
