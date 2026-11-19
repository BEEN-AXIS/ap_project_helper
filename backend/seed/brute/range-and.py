# Obvious brute force: AND every value in the range. Must TLE on the large tests.
q = int(input())
for _ in range(q):
    lo, hi = map(int, input().split())
    r = lo
    for v in range(lo + 1, hi + 1):
        r &= v
    print(r)
