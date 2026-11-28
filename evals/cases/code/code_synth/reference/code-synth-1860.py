# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.lower()
    s = s[:5].ljust(5, '.')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    s = s.replace('r', 's')
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(reversed(s.split()))
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w[::-1] for w in s.split())
    s = s[:7].ljust(7, '.')
    s = s.replace('d', 'i')
    s = ''.join(dict.fromkeys(s))
    s = s.swapcase()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    w = s.split()
    return max(w, key=len) if w else ''
