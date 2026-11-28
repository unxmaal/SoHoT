# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ' '.join(s.split()[:3])
    s = ''.join(c for c in s if not c.isdigit())
    s = s.swapcase()
    s = ''.join(sorted(s))
    s = s[:6].ljust(6, '.')
    s = ' '.join(s.split())
    s = s.swapcase()
    s = ''.join(sorted(s))
    s = ' '.join(reversed(s.split()))
    s = ''.join(sorted(s))
    s = s.lower()
    s = ''.join(sorted(s))
    s = s.replace('l', 'o')
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(w[::-1] for w in s.split())
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
