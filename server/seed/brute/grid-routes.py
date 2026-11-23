import sys
sys.setrecursionlimit(10000)
r, c = map(int, input().split())
g = [input().strip() for _ in range(r)]


def walk(i, j):
    if i >= r or j >= c or g[i][j] == "#":
        return 0
    if i == r - 1 and j == c - 1:
        return 1
    return walk(i + 1, j) + walk(i, j + 1)


print(walk(0, 0) % (10**9 + 7))
