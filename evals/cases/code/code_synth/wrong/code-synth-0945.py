# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(s):
    s = s.lower()
    s = s[:7].ljust(7, '.')
    s = s.lower()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:4])
    s = s.swapcase()
    s = s.lower()
    return len(s.split())
