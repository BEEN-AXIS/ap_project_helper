import sys


def main():
    data = sys.stdin.buffer.read().split()
    n, k = int(data[0]), int(data[1])
    w = list(map(int, data[2:2 + n]))

    def carts(cap):
        used, cur = 1, 0
        for x in w:
            if cur + x > cap:
                used += 1
                cur = x
            else:
                cur += x
        return used

    lo, hi = max(w), sum(w)
    while lo < hi:
        mid = (lo + hi) // 2
        if carts(mid) <= k:
            hi = mid
        else:
            lo = mid + 1
    print(lo)


main()
