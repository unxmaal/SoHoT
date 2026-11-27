# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = s.swapcase()
    s = ' '.join(reversed(s.split()))
    s = ''.join(sorted(s))
    s = s.replace('t', 'n')
    s = ' '.join(reversed(s.split()))
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split())
    s = ' '.join(reversed(s.split()))
    return s
