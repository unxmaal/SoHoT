# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = s[:7].ljust(7, '.')
    s = s.swapcase()
    s = ' '.join(s.split())
    s = s.upper()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.lower()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.replace('d', 'a')
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 12) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(sorted(s))
    s = s.replace('b', 'a')
    s = s.upper()
    s = s.swapcase()
    s = ' '.join(w.capitalize() for w in s.split())
    w = s.split()
    return max(w, key=len) if w else ''
