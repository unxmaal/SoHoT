# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.swapcase()
    s = s[:5].ljust(5, '.')
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split())
    s = s.upper()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.swapcase()
    s = ' '.join(w[::-1] for w in s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(sorted(s))
    w = s.split()
    return max(w, key=len) if w else ''
