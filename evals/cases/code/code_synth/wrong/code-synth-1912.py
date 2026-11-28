# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s[:8].ljust(8, '.')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split()[:2])
    s = s.lower()
    s = s.upper()
    s = s.replace('d', 'i')
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.lower()
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(reversed(s.split()))
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(s.split())
    w = s.split()
    return max(w, key=len) if w else ''
