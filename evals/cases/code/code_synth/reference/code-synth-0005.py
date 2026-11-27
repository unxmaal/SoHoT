# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('c', 'l')
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 3) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.swapcase()
    s = s.upper()
    return len(s)
