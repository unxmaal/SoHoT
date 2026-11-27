# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = s.replace('l', 'c')
    s = ' '.join(s.split()[:3])
    s = s.swapcase()
    s = ' '.join(s.split()[:2])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(reversed(s.split()))
    s = s.upper()
    s = ' '.join(s.split())
    return len(s)
