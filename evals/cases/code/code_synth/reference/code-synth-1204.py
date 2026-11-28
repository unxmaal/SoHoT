# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = s.upper()
    s = ' '.join(s.split()[:3])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.swapcase()
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split())
    s = s.swapcase()
    s = ''.join(dict.fromkeys(s))
    s = s[:6].ljust(6, '.')
    s = ' '.join(s.split())
    s = s[:6].ljust(6, '.')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    return s
