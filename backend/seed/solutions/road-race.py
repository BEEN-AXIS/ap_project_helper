import heapq
import sys


def main():
    data = sys.stdin.buffer.read().split()
    pos = 0
    n, m = int(data[0]), int(data[1]); pos = 2
    adj = [[] for _ in range(n + 1)]
    for _ in range(m):
        u, v, w = int(data[pos]), int(data[pos + 1]), int(data[pos + 2]); pos += 3
        adj[u].append((v, w))
        adj[v].append((u, w))
    q = int(data[pos]); pos += 1
    targets = data[pos:pos + q]
    inf = float("inf")
    dist = [inf] * (n + 1)
    dist[1] = 0
    pq = [(0, 1)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    print("\n".join(str(dist[int(t)]) if dist[int(t)] != inf else "-1" for t in targets))


main()
