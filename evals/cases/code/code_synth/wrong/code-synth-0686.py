# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(s):
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(reversed(s.split()))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.lower()
    s = s.swapcase()
    s = ''.join(sorted(s))
    w = s.split()
    return max(w, key=len) if w else ''
