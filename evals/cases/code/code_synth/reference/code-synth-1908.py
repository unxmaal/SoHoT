# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = s.lower()
    s = ''.join(sorted(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.upper()
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    s = s.upper()
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(sorted(s))
    s = s.replace('c', 'd')
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    s = s.lower()
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
