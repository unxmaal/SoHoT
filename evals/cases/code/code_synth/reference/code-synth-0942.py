# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = s.swapcase()
    s = ' '.join(s.split())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('o', 'e')
    s = s.upper()
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.replace('e', 'l')
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w[::-1] for w in s.split())
    s = s[:6].ljust(6, '.')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    w = s.split()
    return max(w, key=len) if w else ''
