# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = s.lower()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split())
    s = ' '.join(reversed(s.split()))
    s = s.lower()
    s = s[:5].ljust(5, '.')
    w = s.split()
    return max(w, key=len) if w else ''
