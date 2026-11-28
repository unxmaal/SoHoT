# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = ' '.join(s.split())
    s = s.replace('e', 'i')
    s = s.upper()
    s = ' '.join(s.split())
    s = ' '.join(reversed(s.split()))
    s = s[:9].ljust(9, '.')
    s = ' '.join(s.split()[:4])
    s = s.upper()
    s = ''.join(sorted(s))
    s = s.upper()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split())
    s = s.upper()
    s = s.replace('l', 'i')
    s = ' '.join(s.split())
    s = s.lower()
    s = ' '.join(s.split()[:3])
    s = s.swapcase()
    return s
