# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = s.swapcase()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(dict.fromkeys(s))
    s = s[:5].ljust(5, '.')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s[:5].ljust(5, '.')
    s = s.upper()
    s = s.replace('a', 'o')
    s = s.swapcase()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(reversed(s.split()))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    w = s.split()
    return max(w, key=len) if w else ''
