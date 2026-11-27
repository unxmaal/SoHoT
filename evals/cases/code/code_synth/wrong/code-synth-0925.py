# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = s[:5].ljust(5, '.')
    s = ''.join(dict.fromkeys(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.upper()
    s = ' '.join(w[::-1] for w in s.split())
    w = s.split()
    return max(w, key=len) if w else ''
