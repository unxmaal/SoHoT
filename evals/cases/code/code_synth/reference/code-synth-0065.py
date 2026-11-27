# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = s.lower()
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(sorted(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s[:8].ljust(8, '.')
    s = s.replace('l', 'b')
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
