# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 12) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s[:5].ljust(5, '.')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.lower()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    return len(s)
