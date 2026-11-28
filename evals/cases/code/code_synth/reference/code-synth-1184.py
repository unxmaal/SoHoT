# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split()[:3])
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split())
    s = s.swapcase()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split()[:2])
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = s.swapcase()
    s = s[:7].ljust(7, '.')
    w = s.split()
    return max(w, key=len) if w else ''
