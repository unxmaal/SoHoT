# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = ' '.join(s.split()[:2])
    s = ' '.join(reversed(s.split()))
    s = s[:8].ljust(8, '.')
    s = ' '.join(s.split()[:4])
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
