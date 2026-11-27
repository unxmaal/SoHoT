# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = s.swapcase()
    s = ''.join(sorted(s))
    s = s.lower()
    s = ' '.join(w.capitalize() for w in s.split())
    return s
