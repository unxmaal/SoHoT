# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    s = s[:7].ljust(7, '.')
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = s[:8].ljust(8, '.')
    s = s.swapcase()
    s = s.lower()
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('o', 't')
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(dict.fromkeys(s))
    s = s.replace('r', 'n')
    s = ' '.join(w[::-1] for w in s.split())
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split())
    return s
