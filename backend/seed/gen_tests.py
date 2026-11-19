"""Generate hidden tests for the seed problems and write seed/problems/<slug>.json.

Inputs come from fixed-seed generators below; expected outputs come from the
reference solutions in seed/solutions/. The generated files are committed.

    python seed/gen_tests.py            # all problems
    python seed/gen_tests.py range-and  # one problem
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from catalog import PROBLEMS, STUB_HEADER  # noqa: E402

OUT = HERE / "problems"
SOL = HERE / "solutions"


def R(slug: str, i: int) -> random.Random:
    return random.Random(f"{slug}:{i}:algoarena")


def lines(*rows: object) -> str:
    return "\n".join(str(r) for r in rows) + "\n"


def join(xs) -> str:  # type: ignore[no-untyped-def]
    return " ".join(map(str, xs))


# ------------------------------------------------------------------ generators


def g_lonely(slug: str) -> list[str]:
    def make(r: random.Random, pairs: int, lo: int, hi: int) -> str:
        vals = r.sample(range(lo, hi), pairs + 1)
        single, rest = vals[0], vals[1:]
        a = rest + rest + [single]
        r.shuffle(a)
        return lines(len(a), join(a))

    return [
        lines(1, 0),
        lines(1, -1000000000),
        make(R(slug, 1), 3, -5, 5),
        lines(5, join([1000000000, -1000000000, 1000000000, 7, -1000000000])),
        make(R(slug, 2), 8000, -10**9, 10**9),
        make(R(slug, 3), 6000, 0, 100000),
    ]


def g_power(slug: str) -> list[str]:
    r = R(slug, 1)
    edge = [0, 1, 2, 3, 2**59, 2**60 - 1, 10**18, 2**59 + 1, 576460752303423488]
    big = [r.choice([1 << r.randrange(60), r.randrange(10**18 + 1)]) for _ in range(6000)]
    mid = [r.randrange(1, 5000) for _ in range(3000)]
    return [lines(1, 0), lines(1, 1), lines(len(edge), *edge), lines(len(mid), *mid), lines(len(big), *big),
            lines(2000, *([1 << 59] * 2000))]


def g_subset(slug: str) -> list[str]:
    out = [lines(1, 42), lines(11, join(range(89, 100)))]
    for i, n in enumerate((4, 7, 11, 11)):
        out.append(lines(n, join(R(slug, i).sample(range(1, 100), n))))
    return out


def g_gray(slug: str) -> list[str]:
    return [lines(n) for n in (1, 4, 7, 10, 11, 12)]


def g_range_and(slug: str) -> list[str]:
    m = 2**31 - 1
    edge = [(0, 0), (m, m), (0, m), (1, m), (m - 1, m), (2**30, m), (2**30 - 1, 2**30), (12, 15)]
    out = [lines(len(edge), *(f"{a} {b}" for a, b in edge))]
    r = R(slug, 1)
    small = []
    for _ in range(200):
        a = r.randrange(0, 1000)
        small.append((a, a + r.randrange(0, 50)))
    out.append(lines(len(small), *(f"{a} {b}" for a, b in small)))
    r = R(slug, 2)
    same = [(x, x) for x in (r.randrange(m + 1) for _ in range(300))]
    out.append(lines(len(same), *(f"{a} {b}" for a, b in same)))
    for k in (3, 4):
        r = R(slug, k)
        qs = []
        for _ in range(5000):
            a = r.randrange(0, 2**31 - 2**27)
            qs.append((a, a + r.randrange(2**25, 2**27)))  # wide ranges defeat the brute force
        out.append(lines(len(qs), *(f"{a} {b}" for a, b in qs)))
    return out


def g_two_singles(slug: str) -> list[str]:
    def make(r: random.Random, pairs: int, hi: int) -> str:
        vals = r.sample(range(0, hi), pairs + 2)
        a = vals[2:] + vals[2:] + vals[:2]
        r.shuffle(a)
        return lines(len(a), join(a))

    return [
        lines(2, "0 1000000000"),
        lines(4, "5 5 6 7"),
        lines(6, "1 2 3 1 2 1000000000"),
        make(R(slug, 1), 50, 200),
        make(R(slug, 2), 12000, 10**9 + 1),
        make(R(slug, 3), 12000, 10**6),
    ]


def g_max_xor(slug: str) -> list[str]:
    r1, r2 = R(slug, 1), R(slug, 2)
    big1 = [r1.randrange(2**30) for _ in range(45000)]
    big2 = [r2.randrange(2**20) | (r2.randrange(2) << 29) for _ in range(25000)]
    return [
        lines(2, "0 0"),
        lines(2, f"{2**30 - 1} 0"),
        lines(5, "7 7 7 7 7"),
        lines(8, join(R(slug, 3).sample(range(1000), 8))),
        lines(len(big1), join(big1)),
        lines(len(big2), join(big2)),
    ]


def g_xor_basis(slug: str) -> list[str]:
    r = R(slug, 1)
    rank40 = [1 << i for i in range(40)]
    r.shuffle(rank40)
    full = [r.randrange(2**60) for _ in range(8000)]
    return [
        lines(1, 0),
        lines(1, 2**60 - 1),
        lines(6, "3 3 3 3 3 3"),
        lines(5, "1 2 4 8 16"),
        lines(len(rank40), join(rank40)),
        lines(len(full), join(full)),
    ]


def g_first_not_smaller(slug: str) -> list[str]:
    def make(r: random.Random, n: int, q: int, lo: int, hi: int) -> str:
        a = sorted(r.randrange(lo, hi) for _ in range(n))
        qs = [r.randrange(lo - 5, hi + 5) for _ in range(q)]
        return lines(f"{n} {q}", join(a), *qs)

    return [
        lines("1 1", 0, 0),
        lines("3 3", "-1000000000 0 1000000000", -1000000000, 1000000000, 1000000001 - 1),
        lines("6 4", "2 2 2 2 2 2", 1, 2, 3, 2),
        make(R(slug, 1), 100, 100, -50, 50),
        make(R(slug, 2), 20000, 8000, -10**9, 10**9),
        make(R(slug, 3), 20000, 8000, 0, 10),
    ]


def g_split(slug: str) -> list[str]:
    def make(r: random.Random, n: int, k: int, hi: int) -> str:
        return lines(f"{n} {k}", join(r.randrange(hi + 1) for _ in range(n)))

    return [
        lines("1 1", 0),
        lines("1 1", 10000),
        lines("5 3", "0 0 0 0 0"),
        make(R(slug, 1), 30, 4, 20),
        make(R(slug, 2), 30000, 37, 10000),
        make(R(slug, 3), 30000, 29999, 10000),
    ]


def g_balanced(slug: str) -> list[str]:
    r1, r2 = R(slug, 1), R(slug, 2)
    return [
        lines("0"),
        lines("01"),
        lines("1" * 1000),
        lines("".join(r1.choice("01") for _ in range(300))),
        lines("".join(r1.choice("01") for _ in range(200000))),
        lines("01" * 60000),
        lines("".join("0" if r2.random() < 0.52 else "1" for _ in range(120000))),
    ]


def g_ancestor(slug: str) -> list[str]:
    def path_tree(n: int) -> list[int]:
        return [v - 1 for v in range(2, n + 1)]

    def make(r: random.Random, parents: list[int], q: int, deep: bool) -> str:
        n = len(parents) + 1
        depth = [0] * (n + 1)
        for v in range(2, n + 1):
            depth[v] = depth[parents[v - 2]] + 1
        qs = []
        for _ in range(q):
            v = r.randrange(n - n // 10, n + 1) if deep else r.randrange(1, n + 1)
            k = r.randrange(max(0, depth[v] - 50), depth[v] + 2) if deep else r.randrange(0, n + 1)
            qs.append(f"{v} {k}")
        return lines(n, join(parents), q, *qs)

    r = R(slug, 1)
    rand_parents = [r.randrange(1, v) for v in range(2, 2001)]
    return [
        lines(1, "", 2, "1 0", "1 1"),
        lines(2, 1, 3, "2 0", "2 1", "2 2"),
        make(R(slug, 2), rand_parents, 500, False),
        make(R(slug, 3), path_tree(300), 300, False),
        make(R(slug, 4), path_tree(90000), 8000, True),
        make(R(slug, 5), [max(1, v - 1 - (v % 3 == 0)) for v in range(2, 30001)], 8000, True),
    ]


def g_kth(slug: str) -> list[str]:
    def make(r: random.Random, n: int, hi: int, k: int | None = None) -> str:
        a = [r.randrange(hi + 1) for _ in range(n)]
        total = n * (n - 1) // 2
        return lines(f"{n} {k if k else r.randrange(1, total + 1)}", join(a))

    return [
        lines("2 1", "0 1000000000"),
        lines("3 3", "5 5 5"),
        make(R(slug, 1), 50, 100),
        make(R(slug, 2), 500, 10**9, 1),
        make(R(slug, 3), 20000, 10**9),
        make(R(slug, 4), 20000, 1000, 20000 * 19999 // 2),
    ]


def g_stairs(slug: str) -> list[str]:
    return [lines(n) for n in (1, 2, 44, 1000, 999999, 1000000)]


def g_rooms(slug: str) -> list[str]:
    def make(r: random.Random, n: int, span: int, maxlen: int) -> str:
        iv = []
        for _ in range(n):
            s = r.randrange(span)
            iv.append(f"{s} {s + r.randrange(1, maxlen + 1)}")
        return lines(n, *iv)

    return [
        lines(1, "0 1000000000"),
        lines(3, "1 2", "2 3", "3 4"),
        lines(4, "5 9", "5 9", "5 9", "5 9"),
        make(R(slug, 1), 100, 1000, 50),
        make(R(slug, 2), 15000, 10**9 - 10**6, 10**6),
        make(R(slug, 3), 15000, 10**5, 10**4),
    ]


def g_grid(slug: str) -> list[str]:
    def make(r: random.Random, h: int, w: int, p: float) -> str:
        rows = ["".join("#" if r.random() < p else "." for _ in range(w)) for _ in range(h)]
        rows[0] = "." + rows[0][1:]
        rows[-1] = rows[-1][:-1] + "."
        return lines(f"{h} {w}", *rows)

    return [
        lines("1 1", "#"),
        lines("1 5", "....."),
        lines("2 3", "...", "..#"),
        make(R(slug, 1), 12, 12, 0.15),
        make(R(slug, 2), 500, 500, 0.05),
        make(R(slug, 3), 500, 500, 0.0),
    ]


def g_road(slug: str) -> list[str]:
    def make(r: random.Random, n: int, extra: int, q: int, adversarial: bool) -> str:
        edges = [(v, v + 1, r.randrange(1, 100)) for v in range(1, n)] if adversarial else []
        for _ in range(extra):
            u, v = r.randrange(1, n + 1), r.randrange(1, n + 1)
            edges.append((u, v, r.randrange(10**6, 10**9)))
        if adversarial:
            edges.reverse()  # Bellman-Ford then propagates one step per pass
        else:
            r.shuffle(edges)
        targets = [r.randrange(1, n + 1) for _ in range(q)]
        return lines(f"{n} {len(edges)}", *(f"{u} {v} {w}" for u, v, w in edges), q, join(targets))

    return [
        lines("1 0", 1, 1),
        lines("2 0", 2, "1 2"),
        lines("3 3", "1 2 0", "2 3 0", "1 3 5", 3, "1 2 3"),
        make(R(slug, 1), 50, 80, 50, False),
        make(R(slug, 2), 12000, 12000, 5000, True),
        make(R(slug, 3), 10000, 10000, 5000, False),
    ]


GENERATORS = {
    "lonely-number": g_lonely, "power-check": g_power, "subset-parade": g_subset, "gray-ladder": g_gray,
    "range-and": g_range_and, "two-singles": g_two_singles, "max-xor-pair": g_max_xor,
    "xor-basis-count": g_xor_basis, "first-not-smaller": g_first_not_smaller, "split-capacity": g_split,
    "balanced-bits": g_balanced, "ancestor-jumps": g_ancestor, "kth-pair-gap": g_kth, "stair-ways": g_stairs,
    "room-sweep": g_rooms, "grid-routes": g_grid, "road-race": g_road,
}


def run_solution(slug: str, stdin: str) -> str:
    r = subprocess.run([sys.executable, str(SOL / f"{slug}.py")], input=stdin, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"{slug}: reference solution failed:\n{r.stderr}")
    return r.stdout


def build(p: dict) -> dict:
    slug = p["slug"]
    tests = []
    for inp, out in p["samples"]:
        got = run_solution(slug, inp)
        if got.split() != out.split():
            raise RuntimeError(f"{slug}: sample disagrees with the reference\ninput:\n{inp}\nexpected:\n{out}\ngot:\n{got}")
        tests.append({"input": inp, "expected": out, "is_sample": True})
    for inp in GENERATORS[slug](slug):
        if len(inp.encode()) > 1024 * 1024:
            raise RuntimeError(f"{slug}: test input over 1 MB")
        out = run_solution(slug, inp)
        if len(out.encode()) > 64 * 1024:
            raise RuntimeError(f"{slug}: expected output over 64 KB")
        tests.append({"input": inp, "expected": out, "is_sample": False})
    rating = p["rating"]
    tier = 1 if rating < 1200 else 2 if rating < 1400 else 3 if rating < 1600 else 4 if rating < 1900 else 5
    return {
        "slug": slug, "title": p["title"], "biome": p["biome"], "rating": rating,
        "statement_md": p["statement_md"], "input_md": p["input_md"], "output_md": p["output_md"],
        "constraints_md": p["constraints_md"], "tags": p["tags"], "hints": p["hints"],
        "stubs": {"python": STUB_HEADER + p["stub"]},
        "time_limit_ms": 3000 if tier >= 4 else 2000, "memory_mb": 256, "checker": "exact",
        "reference_solution": (SOL / f"{slug}.py").read_text(),
        "tests": tests,
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    only = set(sys.argv[1:])
    for p in PROBLEMS:
        if only and p["slug"] not in only:
            continue
        data = build(p)
        path = OUT / f"{p['slug']}.json"
        path.write_text(json.dumps(data, indent=1) + "\n")
        hidden = sum(1 for t in data["tests"] if not t["is_sample"])
        print(f"{p['slug']:18s} samples={len(data['tests']) - hidden} hidden={hidden} size={path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
