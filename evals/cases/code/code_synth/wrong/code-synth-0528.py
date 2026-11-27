# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = s.lower()
    s = ''.join(sorted(s))
    s = ''.join(dict.fromkeys(s))
    s = s.swapcase()
    s = ' '.join(reversed(s.split()))
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split()[:4])
    s = ''.join(c for c in s if not c.isdigit())
    s = s.lower()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.swapcase()
    return len(s)
