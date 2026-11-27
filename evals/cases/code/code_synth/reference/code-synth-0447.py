# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = s.lower()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.swapcase()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.swapcase()
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(sorted(s))
    return len(s)
