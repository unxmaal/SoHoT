# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = s.upper()
    s = s.replace('n', 'b')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.replace('s', 'i')
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = s.lower()
    s = s.upper()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ' '.join(s.split()[:2])
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    s = ' '.join(s.split()[:3])
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split())
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    w = s.split()
    return max(w, key=len) if w else ''
