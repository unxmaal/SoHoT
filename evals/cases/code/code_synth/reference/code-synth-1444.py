# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 11) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(sorted(s))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split())
    s = s.upper()
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 9) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.upper()
    s = ' '.join(s.split()[:3])
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 3) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(sorted(s))
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = s.lower()
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
