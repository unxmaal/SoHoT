# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split())
    s = s.upper()
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split())
    s = s[:5].ljust(5, '.')
    s = s.replace('a', 'o')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(c for c in s if not c.isdigit())
    s = s[:9].ljust(9, '.')
    s = s.upper()
    s = ' '.join(w[::-1] for w in s.split())
    s = s[:7].ljust(7, '.')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.swapcase()
    return s
