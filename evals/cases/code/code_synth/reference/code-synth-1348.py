# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(sorted(s))
    s = ' '.join(s.split())
    s = s.swapcase()
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 2) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.replace('n', 'l')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w[::-1] for w in s.split())
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    s = s.lower()
    s = ''.join(sorted(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    return s
