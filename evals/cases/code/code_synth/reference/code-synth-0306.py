# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = s.replace('i', 'e')
    s = ' '.join(w[::-1] for w in s.split())
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.swapcase()
    s = ' '.join(w.capitalize() for w in s.split())
    return len(s)
