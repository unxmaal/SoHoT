# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(c for c in s if not c.isdigit())
    s = s.replace('n', 'e')
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s[:7].ljust(7, '.')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 4) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
