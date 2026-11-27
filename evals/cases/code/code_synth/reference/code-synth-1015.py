# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = s.swapcase()
    s = s.lower()
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    return len(s)
