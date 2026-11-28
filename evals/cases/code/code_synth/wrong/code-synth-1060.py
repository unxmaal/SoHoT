# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(s):
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s[:6].ljust(6, '.')
    s = ''.join(dict.fromkeys(s))
    s = s.replace('i', 'b')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s[:8].ljust(8, '.')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 12) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.replace('b', 'e')
    s = s.upper()
    s = ''.join(sorted(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split()[:4])
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
