n = int(input())
line = input().split()
parent = [0, 0] + list(map(int, line))
q = int(input())
for _ in range(q):
    v, k = map(int, input().split())
    while k and v:
        v = parent[v]
        k -= 1
    print(v if v else -1)
