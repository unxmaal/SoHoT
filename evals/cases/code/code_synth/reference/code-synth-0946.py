# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = s.replace('a', 'n')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(s.split()[:3])
    s = s.upper()
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.upper()
    s = s.replace('c', 'i')
    s = ' '.join(reversed(s.split()))
    return s
