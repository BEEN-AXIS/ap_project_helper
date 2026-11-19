import sys

MOD = 10**9 + 7


def main():
    data = sys.stdin.buffer.read().split()
    n = int(data[0])
    basis = [0] * 60
    rank = 0
    for tok in data[1:1 + n]:
        v = int(tok)
        for b in range(59, -1, -1):
            if not v >> b & 1:
                continue
            if not basis[b]:
                basis[b] = v
                rank += 1
                break
            v ^= basis[b]
        if rank == 60:
            break
    print(pow(2, rank, MOD))


main()
