# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split())
    s = s[:8].ljust(8, '.')
    s = ' '.join(s.split())
    s = ' '.join(s.split()[:4])
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 8) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(sorted(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = s[:5].ljust(5, '.')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(reversed(s.split()))
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    w = s.split()
    return max(w, key=len) if w else ''
