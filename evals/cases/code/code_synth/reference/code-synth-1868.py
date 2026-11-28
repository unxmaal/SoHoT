# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(s):
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(s.split()[:2])
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.lower()
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(reversed(s.split()))
    s = s.replace('r', 'i')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(sorted(s))
    s = s.replace('n', 'r')
    s = s.upper()
    s = s.replace('a', 'e')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 8) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
