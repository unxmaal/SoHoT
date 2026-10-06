import heapq


def topo_order(deps):
    nodes = set(deps)
    for ds in deps.values():
        nodes.update(ds)
    waiting = {n: set(deps.get(n, ())) for n in nodes}
    users = {n: [] for n in nodes}
    for n, ds in waiting.items():
        for d in ds:
            users[d].append(n)
    ready = [n for n, ds in waiting.items() if not ds]
    heapq.heapify(ready)
    out = []
    while ready:
        n = heapq.heappop(ready)
        out.append(n)
        for u in users[n]:
            waiting[u].discard(n)
            if not waiting[u]:
                heapq.heappush(ready, u)
    if len(out) != len(nodes):
        raise ValueError("cycle")
    return out
