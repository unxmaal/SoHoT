# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(reversed(s.split()))
    s = s[:5].ljust(5, '.')
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.swapcase()
    s = ' '.join(s.split()[:4])
    s = ''.join(sorted(s))
    return s
