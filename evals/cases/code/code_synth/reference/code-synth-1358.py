# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(s):
    s = s.lower()
    s = ''.join(dict.fromkeys(s))
    s = s.replace('b', 'r')
    s = ' '.join(reversed(s.split()))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(sorted(s))
    s = s[:8].ljust(8, '.')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 12) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 1) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.upper()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(reversed(s.split()))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    return len(s)
