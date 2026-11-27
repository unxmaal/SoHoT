# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = ''.join(sorted(s))
    s = ' '.join(reversed(s.split()))
    s = s[:8].ljust(8, '.')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(sorted(s))
    s = s.lower()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    w = s.split()
    return max(w, key=len) if w else ''
