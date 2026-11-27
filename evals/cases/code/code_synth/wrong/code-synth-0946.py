# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(s):
    s = s.replace('a', 'n')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(s.split()[:3])
    s = s.upper()
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.upper()
    s = s.replace('c', 'i')
    s = ' '.join(reversed(s.split()))
    t = [c.lower() for c in s if c.isalnum()]
    return t == t[::-1]
