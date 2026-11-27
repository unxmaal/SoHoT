# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(s):
    s = ' '.join(reversed(s.split()))
    s = ''.join(sorted(s))
    s = ' '.join(s.split()[:2])
    s = ''.join(c for c in s if not c.isdigit())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.lower()
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    return s
