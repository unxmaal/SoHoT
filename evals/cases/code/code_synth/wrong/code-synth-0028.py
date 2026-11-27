# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    s = ' '.join(s.split()[:3])
    s = s.swapcase()
    s = s[:8].ljust(8, '.')
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(dict.fromkeys(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    w = s.split()
    return max(w, key=len) if w else ''
