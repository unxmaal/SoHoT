# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(s):
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 2) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(dict.fromkeys(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w.capitalize() for w in s.split())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.upper()
    s = s.replace('a', 'n')
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = s.swapcase()
    w = s.split()
    return max(w, key=len) if w else ''
