# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(rows):
    c = {}
    for n, d, s in rows:
        if s >= 60:
            c[d] = c.get(d, 0) + 1
    return c
