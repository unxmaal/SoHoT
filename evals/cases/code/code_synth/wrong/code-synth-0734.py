# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def wrap_text(text):
    lines, cur = [], ''
    for word in text.split():
        if cur and len(cur) + 1 + len(word) <= 19:
            cur += ' ' + word
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines
