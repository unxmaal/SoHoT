# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.swapcase()
    s = ' '.join(s.split()[:3])
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split())
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    w = s.split()
    return max(w, key=len) if w else ''
