# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = ''.join(dict.fromkeys(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.lower()
    s = ' '.join(s.split()[:3])
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split()[:2])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    s = ''.join(c for c in s if not c.isdigit())
    t = [c.lower() for c in s if c.isalnum()]
    return t == t[::-1]
