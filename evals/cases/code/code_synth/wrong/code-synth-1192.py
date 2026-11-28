# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(s.split())
    s = s.upper()
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(w[::-1] for w in s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split()[:2])
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split())
    s = s.upper()
    w = s.split()
    return max(w, key=len) if w else ''
