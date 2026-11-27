# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(s):
    s = s[:6].ljust(6, '.')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    s = s.replace('i', 'e')
    s = ''.join(sorted(s))
    s = ' '.join(s.split()[:4])
    return s
