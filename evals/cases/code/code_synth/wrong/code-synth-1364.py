# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = s.lower()
    s = s.replace('t', 's')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.upper()
    s = ''.join(c for c in s if not c.isdigit())
    s = s.swapcase()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.lower()
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(reversed(s.split()))
    s = s.upper()
    s = ' '.join(s.split()[:2])
    return s
