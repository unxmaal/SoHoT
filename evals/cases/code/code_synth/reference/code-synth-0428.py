# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(s):
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s[:7].ljust(7, '.')
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(sorted(s))
    return s
