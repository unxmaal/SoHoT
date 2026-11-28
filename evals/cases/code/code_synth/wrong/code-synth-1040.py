# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = s.upper()
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w[::-1] for w in s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split()[:4])
    s = s.swapcase()
    s = ''.join(dict.fromkeys(s))
    s = s.swapcase()
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(dict.fromkeys(s))
    return len(s)
