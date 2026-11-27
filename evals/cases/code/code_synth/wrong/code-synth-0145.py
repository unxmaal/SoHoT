# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    s = ''.join(sorted(s))
    s = s.swapcase()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s[:9].ljust(9, '.')
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if not c.isdigit())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    return s
