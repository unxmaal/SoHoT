# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.upper()
    s = s.lower()
    s = ' '.join(reversed(s.split()))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 12) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s[:6].ljust(6, '.')
    s = s.swapcase()
    s = ' '.join(reversed(s.split()))
    s = s.lower()
    s = ' '.join(s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(s.split()[:4])
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ' '.join(w.capitalize() for w in s.split())
    return s
