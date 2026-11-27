# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(s):
    s = ''.join(sorted(s))
    s = s.upper()
    s = ' '.join(s.split()[:4])
    s = ' '.join(s.split())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.upper()
    w = s.split()
    return max(w, key=len) if w else ''
