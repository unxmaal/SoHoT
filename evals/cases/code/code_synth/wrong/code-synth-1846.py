# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(s):
    s = s.lower()
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:4])
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.replace('l', 'i')
    s = ' '.join(s.split()[:3])
    s = ' '.join(reversed(s.split()))
    s = s.lower()
    s = ''.join(sorted(s))
    s = s[:7].ljust(7, '.')
    s = s.upper()
    s = ' '.join(s.split())
    s = ' '.join(s.split()[:2])
    w = s.split()
    return max(w, key=len) if w else ''
