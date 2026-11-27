# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(sorted(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 7) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s[:5].ljust(5, '.')
    s = s.swapcase()
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
