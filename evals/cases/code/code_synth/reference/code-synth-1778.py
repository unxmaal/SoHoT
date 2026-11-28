# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.lower()
    s = s.upper()
    s = s.lower()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split()[:4])
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 9) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s[:7].ljust(7, '.')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.lower()
    return s
