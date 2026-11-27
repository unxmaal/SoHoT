# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('t', 'n')
    s = ''.join(c for c in s if not c.isdigit())
    s = s.upper()
    s = ' '.join(w[::-1] for w in s.split())
    s = s[:8].ljust(8, '.')
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
