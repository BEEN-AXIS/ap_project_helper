n, k = map(int, input().split())
a = list(map(int, input().split()))
d = sorted(abs(a[i] - a[j]) for i in range(n) for j in range(i + 1, n))
print(d[k - 1])
