# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = ' '.join(w.capitalize() for w in s.split())
    s = s[:9].ljust(9, '.')
    s = s.lower()
    s = s.swapcase()
    s = ' '.join(s.split()[:4])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    w = s.split()
    return max(w, key=len) if w else ''
