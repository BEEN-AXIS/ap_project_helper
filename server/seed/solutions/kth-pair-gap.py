import sys


def main():
    data = sys.stdin.buffer.read().split()
    n, k = int(data[0]), int(data[1])
    a = sorted(map(int, data[2:2 + n]))

    def count_at_most(d):
        cnt = 0
        i = 0
        for j in range(n):
            while a[j] - a[i] > d:
                i += 1
            cnt += j - i
        return cnt

    lo, hi = 0, a[-1] - a[0]
    while lo < hi:
        mid = (lo + hi) // 2
        if count_at_most(mid) >= k:
            hi = mid
        else:
            lo = mid + 1
    print(lo)


main()
