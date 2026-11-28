# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = ' '.join(reversed(s.split()))
    s = s.swapcase()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.swapcase()
    s = ' '.join(w[::-1] for w in s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(reversed(s.split()))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 7) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 10) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.replace('a', 'o')
    s = s[:9].ljust(9, '.')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.replace('c', 'o')
    w = s.split()
    return max(w, key=len) if w else ''
