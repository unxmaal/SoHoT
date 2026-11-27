# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(s):
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:2])
    s = ' '.join(w.capitalize() for w in s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    w = s.split()
    return max(w, key=len) if w else ''
