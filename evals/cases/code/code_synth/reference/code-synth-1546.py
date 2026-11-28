# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = s.swapcase()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    s = s.replace('e', 't')
    s = ''.join(sorted(s))
    s = s[:7].ljust(7, '.')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.swapcase()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.replace('e', 'a')
    s = ' '.join(s.split())
    s = ''.join(sorted(s))
    s = s.upper()
    s = s.lower()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    w = s.split()
    return max(w, key=len) if w else ''
