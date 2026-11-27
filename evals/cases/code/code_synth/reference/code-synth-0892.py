# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(s):
    s = ' '.join(reversed(s.split()))
    s = ' '.join(w[::-1] for w in s.split())
    s = s.lower()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    return s
