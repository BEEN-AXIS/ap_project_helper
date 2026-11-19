MOD = 10**9 + 7


def main():
    n = int(input())
    a, b = 1, 1
    for _ in range(n - 1):
        a, b = b, (a + b) % MOD
    print(b)


main()
