# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = ' '.join(reversed(s.split()))
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = s.replace('c', 'r')
    s = s.lower()
    s = ' '.join(s.split())
    s = s[:8].ljust(8, '.')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    return s
