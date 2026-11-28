# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s[:6].ljust(6, '.')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 4) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(c for c in s if not c.isdigit())
    s = s.lower()
    s = ''.join(dict.fromkeys(s))
    s = s.lower()
    s = ' '.join(s.split())
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(sorted(s))
    s = ' '.join(s.split())
    return s
