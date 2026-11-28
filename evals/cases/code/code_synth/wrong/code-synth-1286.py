# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = ''.join(sorted(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(w[::-1] for w in s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 1) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(dict.fromkeys(s))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 7) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = ''.join(sorted(s))
    s = s.upper()
    return len(s)
