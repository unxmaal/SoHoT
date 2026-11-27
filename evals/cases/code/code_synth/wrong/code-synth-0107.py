# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(s):
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.upper()
    s = ' '.join(s.split()[:2])
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    return s
