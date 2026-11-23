import sys


def main():
    data = sys.stdin.buffer.read().split()
    n = int(data[0])
    r = 0
    for x in data[1:1 + n]:
        r ^= int(x)
    print(r)


main()
