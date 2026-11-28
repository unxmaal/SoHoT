# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = s.swapcase()
    s = s.lower()
    s = ''.join(c for c in s if not c.isdigit())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 5) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(sorted(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(s.split())
    s = s.lower()
    s = ' '.join(s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s[:5].ljust(5, '.')
    s = s.upper()
    s = ' '.join(s.split()[:4])
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 9) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.swapcase()
    s = ''.join(sorted(s))
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
