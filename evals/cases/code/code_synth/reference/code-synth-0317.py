# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def min_jumps(grid, start, goal):
    from collections import deque
    h, w = len(grid), len(grid[0])
    jumps = {(sa * x, sb * y) for x, y in ((1, 4), (4, 1)) for sa in (1, -1) for sb in (1, -1)}
    dist, queue = {start: 0}, deque([start])
    while queue:
        cur = queue.popleft()
        for dr, dc in jumps:
            nxt = (cur[0] + dr, cur[1] + dc)
            if 0 <= nxt[0] < h and 0 <= nxt[1] < w and grid[nxt[0]][nxt[1]] != '#' and nxt not in dist:
                dist[nxt] = dist[cur] + 1
                queue.append(nxt)
    return dist.get(goal, -1)
