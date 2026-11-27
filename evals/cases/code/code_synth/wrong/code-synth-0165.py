# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(s):
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.swapcase()
    s = ' '.join(reversed(s.split()))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(reversed(s.split()))
    s = s.lower()
    s = ' '.join(reversed(s.split()))
    s = ' '.join(w.capitalize() for w in s.split())
    w = s.split()
    return max(w, key=len) if w else ''
