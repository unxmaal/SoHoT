# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(reversed(s.split()))
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    w = s.split()
    return max(w, key=len) if w else ''
