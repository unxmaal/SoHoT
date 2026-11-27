# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ''.join(dict.fromkeys(s))
    s = s.lower()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.upper()
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split()[:2])
    s = s.swapcase()
    s = ' '.join(s.split()[:2])
    return len(s.split())
