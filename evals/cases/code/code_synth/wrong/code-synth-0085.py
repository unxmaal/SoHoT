# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split()[:3])
    s = ''.join(sorted(s))
    s = ' '.join(s.split())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.upper()
    w = s.split()
    return max(w, key=len) if w else ''
