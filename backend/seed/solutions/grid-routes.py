import sys

MOD = 10**9 + 7


def main():
    data = sys.stdin.read().split()
    r, c = int(data[0]), int(data[1])
    g = data[2:2 + r]
    dp = [0] * c
    for i in range(r):
        row = g[i]
        for j in range(c):
            if row[j] == "#":
                dp[j] = 0
            elif i == 0 and j == 0:
                dp[j] = 1
            elif j:
                dp[j] = (dp[j] + dp[j - 1]) % MOD
    print(dp[c - 1])


main()
