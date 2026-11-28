# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(s):
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(s.split())
    s = ''.join(dict.fromkeys(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(s.split())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(reversed(s.split()))
    s = s.replace('t', 'a')
    s = s[:6].ljust(6, '.')
    s = s.swapcase()
    s = ' '.join(s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.swapcase()
    s = s.upper()
    w = s.split()
    return max(w, key=len) if w else ''
