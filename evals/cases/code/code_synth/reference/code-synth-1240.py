# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.replace('c', 'd')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.lower()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.swapcase()
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 1) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split())
    return s
