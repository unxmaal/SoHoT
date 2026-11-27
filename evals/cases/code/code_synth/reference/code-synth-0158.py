# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def merge_spans(spans):
    out = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1] + 3:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out
