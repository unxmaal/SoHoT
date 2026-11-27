# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.replace('l', 'd')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split())
    s = s.lower()
    s = s.upper()
    s = ''.join(sorted(s))
    s = ' '.join(s.split()[:2])
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
