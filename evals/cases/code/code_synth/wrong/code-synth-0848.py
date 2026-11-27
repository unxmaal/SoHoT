# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(s):
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split()[:3])
    s = s.upper()
    s = ' '.join(w[::-1] for w in s.split())
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
