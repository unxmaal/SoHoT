# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = s.replace('c', 'b')
    s = ' '.join(s.split()[:4])
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    s = s.lower()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(sorted(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
