# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.upper()
    s = s.replace('n', 'l')
    s = ''.join(sorted(s))
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(reversed(s.split()))
    s = s.replace('c', 'r')
    s = s[:8].ljust(8, '.')
    s = s.swapcase()
    s = ' '.join(reversed(s.split()))
    s = s.swapcase()
    s = s.upper()
    return s
