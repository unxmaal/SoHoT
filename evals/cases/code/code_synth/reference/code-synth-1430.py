# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(reversed(s.split()))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 1) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(reversed(s.split()))
    s = s.lower()
    s = s.upper()
    s = ' '.join(s.split())
    s = ''.join(dict.fromkeys(s))
    s = s.lower()
    s = ''.join(sorted(s))
    s = s.upper()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    w = s.split()
    return max(w, key=len) if w else ''
