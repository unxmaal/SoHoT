# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = s.swapcase()
    s = ' '.join(s.split()[:2])
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 8) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(s.split()[:3])
    s = ' '.join(s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split()[:3])
    s = s.swapcase()
    s = ' '.join(reversed(s.split()))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 1) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 3) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s[:5].ljust(5, '.')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    w = s.split()
    return max(w, key=len) if w else ''
