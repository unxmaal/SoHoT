# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = s.lower()
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = s.swapcase()
    s = ' '.join(s.split())
    s = ''.join(dict.fromkeys(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.swapcase()
    s = ' '.join(s.split())
    return s
