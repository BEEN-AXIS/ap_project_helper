import sys


def main():
    data = sys.stdin.buffer.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1 + n]))
    ans = 0
    mask = 0
    for b in range(29, -1, -1):
        mask |= 1 << b
        pre = {v & mask for v in a}
        cand = ans | (1 << b)
        for p in pre:
            if cand ^ p in pre:
                ans = cand
                break
    print(ans)


main()
