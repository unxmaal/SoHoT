# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = s.swapcase()
    s = s.lower()
    s = s.replace('s', 'c')
    s = ' '.join(s.split()[:3])
    s = ''.join(dict.fromkeys(s))
    return len(s)
