import sys


def main():
    s = sys.stdin.readline().strip()
    seen = {0: 1}
    bal = 0
    ans = 0
    for ch in s:
        bal += 1 if ch == "1" else -1
        c = seen.get(bal, 0)
        ans += c
        seen[bal] = c + 1
    print(ans)


main()
