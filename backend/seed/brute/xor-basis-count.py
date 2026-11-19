n = int(input())
s = {0}
for v in map(int, input().split()):
    s |= {x ^ v for x in s}
print(len(s) % (10**9 + 7))
