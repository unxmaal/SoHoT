# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(dict.fromkeys(s))
    s = s.swapcase()
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split()[:4])
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(sorted(s))
    s = s.upper()
    s = s.replace('n', 'r')
    w = s.split()
    return max(w, key=len) if w else ''
