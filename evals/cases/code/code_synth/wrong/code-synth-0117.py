# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def cache_hits(seq):
    cache, hits = [], 0
    for x in seq:
        if x in cache:
            hits += 1
            cache.remove(x)
            cache.append(x)
        else:
            if len(cache) == 4:
                cache.pop(0)
            cache.append(x)
    return hits
