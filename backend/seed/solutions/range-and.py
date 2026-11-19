import sys


def main():
    data = sys.stdin.buffer.read().split()
    q = int(data[0])
    out = []
    for i in range(q):
        lo, hi = int(data[1 + 2 * i]), int(data[2 + 2 * i])
        shift = 0
        while lo != hi:
            lo >>= 1
            hi >>= 1
            shift += 1
        out.append(str(lo << shift))
    print("\n".join(out))


main()
