# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ''.join(sorted(s))
    s = s[:8].ljust(8, '.')
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    s = s.replace('d', 'n')
    s = ''.join(sorted(s))
    s = ' '.join(s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 7) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.swapcase()
    s = ' '.join(reversed(s.split()))
    return len(s)
