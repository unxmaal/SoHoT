# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ' '.join(s.split()[:4])
    s = ' '.join(reversed(s.split()))
    s = s.upper()
    s = s.swapcase()
    s = s.upper()
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 4) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ' '.join(s.split())
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ' '.join(s.split()[:2])
    s = s.replace('d', 'a')
    s = s.lower()
    s = ' '.join(s.split()[:2])
    s = s.replace('b', 'r')
    s = s.upper()
    return s
