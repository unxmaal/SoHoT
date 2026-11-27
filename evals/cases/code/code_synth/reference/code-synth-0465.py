# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = s.lower()
    s = s.swapcase()
    s = s.replace('s', 'c')
    s = ' '.join(s.split()[:3])
    s = ''.join(dict.fromkeys(s))
    return len(s)
