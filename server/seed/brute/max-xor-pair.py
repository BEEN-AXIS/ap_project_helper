n = int(input())
a = list(map(int, input().split()))
print(max(a[i] ^ a[j] for i in range(n) for j in range(i + 1, n)))
