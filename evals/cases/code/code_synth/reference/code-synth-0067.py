# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(s):
    s = s.upper()
    s = s.replace('o', 's')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split()[:4])
    s = ''.join(sorted(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    return len(s)
