# Bellman-Ford: O(n * m). Must TLE on the large tests.
n, m = map(int, input().split())
edges = [tuple(map(int, input().split())) for _ in range(m)]
INF = float("inf")
dist = [INF] * (n + 1)
dist[1] = 0
for _ in range(n - 1):
    changed = False
    for u, v, w in edges:
        if dist[u] + w < dist[v]:
            dist[v] = dist[u] + w; changed = True
        if dist[v] + w < dist[u]:
            dist[u] = dist[v] + w; changed = True
    if not changed:
        break
q = int(input())
for t in map(int, input().split()):
    print(dist[t] if dist[t] != INF else -1)
