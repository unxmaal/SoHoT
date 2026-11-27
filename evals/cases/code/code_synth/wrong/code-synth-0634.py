# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def merge_spans(spans):
    out = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1] + 6:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out
