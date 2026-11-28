# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = s[:6].ljust(6, '.')
    s = ' '.join(reversed(s.split()))
    s = s.replace('i', 'r')
    s = s.swapcase()
    s = s.replace('n', 'r')
    s = ' '.join(w.capitalize() for w in s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s[:8].ljust(8, '.')
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 12) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(dict.fromkeys(s))
    s = s.replace('b', 'r')
    s = ''.join(sorted(s))
    return len(s.split())
