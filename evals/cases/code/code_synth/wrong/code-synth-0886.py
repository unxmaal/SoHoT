# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    s = ' '.join(s.split()[:4])
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(sorted(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    return len(s)
