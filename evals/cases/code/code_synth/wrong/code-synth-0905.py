# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(s):
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.replace('i', 's')
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w.capitalize() for w in s.split())
    s = s[:5].ljust(5, '.')
    s = s.swapcase()
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
