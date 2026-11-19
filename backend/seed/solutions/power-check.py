import sys


def main():
    data = sys.stdin.buffer.read().split()
    q = int(data[0])
    out = []
    for x in data[1:1 + q]:
        v = int(x)
        out.append("YES" if v > 0 and v & (v - 1) == 0 else "NO")
    print("\n".join(out))


main()
