# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = s[:6].ljust(6, '.')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.replace('d', 't')
    s = ' '.join(s.split()[:3])
    s = s[:5].ljust(5, '.')
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 10) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s[:9].ljust(9, '.')
    s = ''.join(sorted(s))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 10) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.replace('r', 'b')
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:3])
    s = ' '.join(reversed(s.split()))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.lower()
    s = ''.join(sorted(s))
    s = s[:7].ljust(7, '.')
    s = s.upper()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    return s
