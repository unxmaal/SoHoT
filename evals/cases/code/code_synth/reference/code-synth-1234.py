# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = s[:8].ljust(8, '.')
    s = s.replace('t', 'l')
    s = s.swapcase()
    s = s.upper()
    s = ' '.join(s.split()[:3])
    s = s.replace('n', 'e')
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w[::-1] for w in s.split())
    s = s.upper()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ' '.join(reversed(s.split()))
    s = s.swapcase()
    return s
