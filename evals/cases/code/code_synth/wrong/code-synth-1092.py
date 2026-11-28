# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('b', 'e')
    s = s.lower()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.lower()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split()[:4])
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split())
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split())
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:2])
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w.capitalize() for w in s.split())
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
