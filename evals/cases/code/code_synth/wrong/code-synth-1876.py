# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 3) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(w[::-1] for w in s.split())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s[:9].ljust(9, '.')
    s = s.replace('b', 'e')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(reversed(s.split()))
    s = s.upper()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split())
    s = s[:6].ljust(6, '.')
    s = s.swapcase()
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.replace('a', 'e')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.replace('d', 'n')
    return s
