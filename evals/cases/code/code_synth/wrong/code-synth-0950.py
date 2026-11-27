# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(s):
    s = s.swapcase()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.swapcase()
    s = s.replace('i', 'c')
    s = s.lower()
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    w = s.split()
    return max(w, key=len) if w else ''
