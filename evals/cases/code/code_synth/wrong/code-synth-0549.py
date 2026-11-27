# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ' '.join(s.split())
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('r', 'a')
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.upper()
    return s
