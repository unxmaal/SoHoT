# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ''.join(c for c in s if not c.isdigit())
    s = s[:5].ljust(5, '.')
    s = ' '.join(s.split()[:2])
    s = ' '.join(w[::-1] for w in s.split())
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(reversed(s.split()))
    t = [c.lower() for c in s if c.isalnum()]
    return t == t[::-1]
