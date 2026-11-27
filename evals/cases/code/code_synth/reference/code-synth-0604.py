# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = s.upper()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ' '.join(reversed(s.split()))
    s = s[:8].ljust(8, '.')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.replace('d', 'l')
    s = ' '.join(reversed(s.split()))
    s = ' '.join(w[::-1] for w in s.split())
    return len(s.split())
