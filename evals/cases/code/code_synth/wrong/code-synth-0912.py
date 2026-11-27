# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = s[:7].ljust(7, '.')
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.lower()
    s = ' '.join(s.split()[:4])
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
