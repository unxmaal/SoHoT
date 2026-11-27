# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def earliest_arrival(n, edges):
    import heapq
    best, heap = {0: 0}, [(0, 0)]
    while heap:
        t, u = heapq.heappop(heap)
        if t > best.get(u, float('inf')):
            continue
        for a, b, w, p, o in edges:
            if a != u:
                continue
            start = t + (o - t) % p
            if start < t:
                start = t
            arrive = start + w
            if arrive < best.get(b, float('inf')):
                best[b] = arrive
                heapq.heappush(heap, (arrive, b))
    return best.get(n - 1, -1)
