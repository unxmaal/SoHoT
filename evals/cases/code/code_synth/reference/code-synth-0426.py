# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    s = s.replace('b', 'c')
    s = ' '.join(s.split()[:3])
    s = ' '.join(s.split())
    s = s.upper()
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(dict.fromkeys(s))
    return len(s)
