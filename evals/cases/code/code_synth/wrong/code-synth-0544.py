# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(s):
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('e', 'i')
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = s.swapcase()
    return len(s.split())
