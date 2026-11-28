# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = s.replace('i', 'r')
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split()[:2])
    s = ''.join(c for c in s if not c.isdigit())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 3) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(s.split()[:3])
    s = s.upper()
    s = s.replace('l', 'i')
    s = s.swapcase()
    s = ''.join(dict.fromkeys(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.replace('e', 'c')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ' '.join(w[::-1] for w in s.split())
    return len(s)
