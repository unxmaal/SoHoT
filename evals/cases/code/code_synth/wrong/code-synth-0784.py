# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(s):
    s = s.replace('i', 'l')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    w = s.split()
    return max(w, key=len) if w else ''
