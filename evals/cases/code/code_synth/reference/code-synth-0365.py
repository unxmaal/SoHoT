# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = s[:9].ljust(9, '.')
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:3])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.upper()
    s = s.swapcase()
    s = s[:6].ljust(6, '.')
    s = s.lower()
    return s
