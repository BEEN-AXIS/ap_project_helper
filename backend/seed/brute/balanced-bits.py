s = input().strip()
n = len(s)
ans = 0
for i in range(n):
    bal = 0
    for j in range(i, n):
        bal += 1 if s[j] == "1" else -1
        if bal == 0:
            ans += 1
print(ans)
