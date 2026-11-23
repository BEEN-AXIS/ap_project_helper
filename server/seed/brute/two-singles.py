# Obvious brute force: count every value with a nested loop. Must TLE on the large tests.
n = int(input())
a = list(map(int, input().split()))
out = []
for i in range(n):
    c = 0
    for j in range(n):
        if a[j] == a[i]:
            c += 1
    if c == 1:
        out.append(a[i])
print(*sorted(out))
