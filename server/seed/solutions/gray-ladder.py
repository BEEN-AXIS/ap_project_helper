def main():
    n = int(input())
    print("\n".join(format(i ^ (i >> 1), f"0{n}b") for i in range(1 << n)))


main()
