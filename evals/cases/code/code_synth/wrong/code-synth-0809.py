# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split())
    s = s.replace('t', 'b')
    s = s[:7].ljust(7, '.')
    s = ' '.join(s.split()[:4])
    s = s.upper()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    return s
