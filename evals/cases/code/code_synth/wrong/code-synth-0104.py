# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = s.swapcase()
    s = ''.join(sorted(s))
    s = s.lower()
    s = ' '.join(w.capitalize() for w in s.split())
    t = [c.lower() for c in s if c.isalnum()]
    return t == t[::-1]
