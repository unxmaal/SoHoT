# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(sorted(s))
    s = ' '.join(s.split()[:2])
    s = s.upper()
    s = ' '.join(s.split())
    s = s.upper()
    s = s.lower()
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.swapcase()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    return len(s)
