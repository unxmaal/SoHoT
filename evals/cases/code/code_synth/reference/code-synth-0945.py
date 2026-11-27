# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(s):
    s = s.lower()
    s = s[:7].ljust(7, '.')
    s = s.lower()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:4])
    s = s.swapcase()
    s = s.lower()
    w = s.split()
    return max(w, key=len) if w else ''
