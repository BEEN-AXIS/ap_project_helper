import sys


def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    a = data[1:1 + n]
    out = []
    for m in range(1 << n):
        part = [a[i] for i in range(n) if m >> i & 1]
        out.append(" ".join(part) if part else "-")
    print("\n".join(out))


main()
