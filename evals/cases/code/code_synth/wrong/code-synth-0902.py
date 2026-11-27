# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(s):
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = s.replace('s', 'c')
    s = s.lower()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(sorted(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split())
    s = ''.join(sorted(s))
    s = s.replace('r', 'i')
    s = s.upper()
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
