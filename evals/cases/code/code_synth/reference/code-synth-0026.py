# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = ''.join(sorted(s))
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    s = ' '.join(s.split())
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split())
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
