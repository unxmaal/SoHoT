# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(s):
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 4) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.lower()
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = s.lower()
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.upper()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.upper()
    s = ' '.join(s.split()[:4])
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    s = s.swapcase()
    w = s.split()
    return max(w, key=len) if w else ''
