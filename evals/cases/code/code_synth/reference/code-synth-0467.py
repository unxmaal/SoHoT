# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = s.lower()
    s = ' '.join(s.split())
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = s.replace('a', 'n')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    s = s[:8].ljust(8, '.')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    w = s.split()
    return max(w, key=len) if w else ''
