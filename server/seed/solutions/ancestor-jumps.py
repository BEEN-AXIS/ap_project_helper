import sys


def main():
    data = sys.stdin.buffer.read().split()
    pos = 0
    n = int(data[pos]); pos += 1
    parent = [0] * (n + 1)
    for v in range(2, n + 1):
        parent[v] = int(data[pos]); pos += 1
    log = max(1, n.bit_length())
    up = [parent]
    for _ in range(1, log):
        prev = up[-1]
        up.append([prev[prev[v]] for v in range(n + 1)])
    q = int(data[pos]); pos += 1
    out = []
    for _ in range(q):
        v, k = int(data[pos]), int(data[pos + 1]); pos += 2
        if k >= (1 << log):
            out.append("-1")
            continue
        j = 0
        while k and v:
            if k & 1:
                v = up[j][v]
            k >>= 1
            j += 1
        out.append(str(v) if v else "-1")
    print("\n".join(out))


main()
