# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(rows):
    t = {}
    for n, d, s in rows:
        t[d] = t.get(d, 0) + s
    return min(t, key=lambda d: (-t[d], d)) if t else None
