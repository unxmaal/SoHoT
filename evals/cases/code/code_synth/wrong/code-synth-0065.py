# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(s):
    s = s.lower()
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(sorted(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s[:8].ljust(8, '.')
    s = s.replace('l', 'b')
    w = s.split()
    return max(w, key=len) if w else ''
