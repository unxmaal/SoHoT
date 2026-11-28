# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = ' '.join(s.split()[:2])
    s = ''.join(sorted(s))
    s = s.upper()
    s = s[:8].ljust(8, '.')
    s = s.upper()
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 2) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(w[::-1] for w in s.split())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(dict.fromkeys(s))
    s = s.swapcase()
    s = s[:8].ljust(8, '.')
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = s.swapcase()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = s[:5].ljust(5, '.')
    s = ' '.join(w[::-1] for w in s.split())
    w = s.split()
    return max(w, key=len) if w else ''
