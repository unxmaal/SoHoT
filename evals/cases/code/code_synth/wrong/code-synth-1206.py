# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(s):
    s = ' '.join(s.split()[:3])
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split())
    s = s.swapcase()
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split()[:4])
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(reversed(s.split()))
    s = s.swapcase()
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    return s
