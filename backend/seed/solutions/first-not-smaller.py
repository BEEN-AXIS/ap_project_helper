import sys
from bisect import bisect_left


def main():
    data = sys.stdin.buffer.read().split()
    n, q = int(data[0]), int(data[1])
    a = list(map(int, data[2:2 + n]))
    qs = data[2 + n:2 + n + q]
    print("\n".join(str(bisect_left(a, int(x))) for x in qs))


main()
