# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def wrap_text(text):
    lines, cur = [], ''
    for word in text.split():
        if cur and len(cur) + 1 + len(word) <= 11:
            cur += ' ' + word
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines
