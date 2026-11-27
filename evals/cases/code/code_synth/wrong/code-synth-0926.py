# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = s.swapcase()
    s = ' '.join(s.split()[:4])
    s = s.replace('s', 'o')
    s = ''.join(sorted(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
