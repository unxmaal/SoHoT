# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 8) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.lower()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s[:6].ljust(6, '.')
    s = ' '.join(s.split())
    s = ' '.join(s.split()[:2])
    s = s.lower()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ' '.join(reversed(s.split()))
    s = s.swapcase()
    s = s.lower()
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
