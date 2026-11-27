# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = s.lower()
    s = s.upper()
    s = ''.join(c for c in s if not c.isdigit())
    s = s.replace('a', 'l')
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split())
    return len(s)
