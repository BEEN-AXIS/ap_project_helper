import sys


def main():
    data = sys.stdin.buffer.read().split()
    n = int(data[0])
    a = list(map(int, data[1:1 + n]))
    s = 0
    for v in a:
        s ^= v
    low = s & -s
    x = 0
    for v in a:
        if v & low:
            x ^= v
    y = s ^ x
    print(min(x, y), max(x, y))


main()
