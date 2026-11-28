# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split()[:2])
    s = ''.join(c for c in s if not c.isdigit())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.lower()
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.replace('t', 'a')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(sorted(s))
    s = ''.join(dict.fromkeys(s))
    s = ''.join(sorted(s))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 2) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(s.split()[:3])
    s = s.swapcase()
    w = s.split()
    return max(w, key=len) if w else ''
