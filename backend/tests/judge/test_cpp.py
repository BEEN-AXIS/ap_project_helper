"""C++ through the real compiler and the shared harness (dev runner).

Skipped when no g++ is installed. Covers every verdict, the bundled
<bits/stdc++.h>, deep recursion, compile errors without temp paths, a
missing compiler, the dev-sandbox tripwire and the test judge's // markers.
"""

from __future__ import annotations

import shutil
from dataclasses import replace

import pytest

from app.core.config import load_game_config_file
from app.judge import build_job, language_tools_present
from app.judge.fake_runner import FakeRunner
from app.judge.runner import TestCase, TestVerdict
from app.judge.subprocess_runner import SubprocessRunner, cpp_tripwire

CFG = load_game_config_file()
needs_gxx = pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
pytestmark = pytest.mark.anyio

SUM = "#include <bits/stdc++.h>\nusing namespace std;\nint main(){ios::sync_with_stdio(false);cin.tie(nullptr);long long a,b;cin>>a>>b;cout<<a+b<<'\\n';}\n"
TESTS = [TestCase(0, "1 2\n", "3", True), TestCase(1, "1000000000000 1\n", "1000000000001", False)]


def job(src: str, tests: list[TestCase] = TESTS, tl: int = 1000, mem: int = 256, mode: str = "full"):  # type: ignore[no-untyped-def]
    return build_job(cfg=CFG, language="cpp", source=src, tests=tests, mode=mode, time_limit_ms=tl, memory_mb=mem, checker="tokens")


async def run(j):  # type: ignore[no-untyped-def]
    seen: list[TestVerdict] = []

    async def progress(v: TestVerdict) -> None:
        seen.append(v)

    res = await SubprocessRunner("test").run(j, progress)
    return res, seen


def test_config_and_job_shape() -> None:
    cpp = CFG.language("cpp")
    assert cpp.time_multiplier == 1 and cpp.comment == "//" and cpp.compile and "{include}" in cpp.compile
    j = job(SUM)
    assert j.compile_argv and j.compile_argv[0] == "g++" and j.run_argv == ["./main"] and j.file == "main.cpp"
    py = build_job(cfg=CFG, language="python", source="print(1)", tests=TESTS, mode="full", time_limit_ms=1000, memory_mb=256, checker="exact")
    assert py.compile_argv is None and py.limits.time_ms == 8 * j.limits.time_ms  # limits are set for C++


@needs_gxx
async def test_accepted_with_bits_stdcxx_and_streams_progress() -> None:
    res, seen = await run(job(SUM))
    assert res.compile_error is None and [v.code for v in res.verdicts] == ["AC", "AC"]
    assert [v.index for v in seen] == [0, 1]


@needs_gxx
async def test_wrong_answer_stops_at_the_first_failure() -> None:
    res, _ = await run(job(SUM.replace("a+b", "a-b")))
    assert [v.code for v in res.verdicts] == ["WA"]


@needs_gxx
async def test_compile_error_shows_the_compiler_message_without_temp_paths() -> None:
    res, _ = await run(job("#include <bits/stdc++.h>\nint main(){ undeclared_thing = 1; }\n"))
    assert res.compile_error and "undeclared_thing" in res.compile_error and "error" in res.compile_error
    assert "aa-job-" not in res.compile_error and "/tmp" not in res.compile_error
    assert res.compile_error.splitlines()[0].startswith("main.cpp:")
    assert res.verdicts == []


@needs_gxx
async def test_runtime_errors_time_limit_and_memory() -> None:
    one = [TestCase(0, "\n", "0", False)]
    segv, _ = await run(job("int main(){ volatile int* p = nullptr; return *p; }", one))
    assert segv.verdicts[0].code == "RE"
    nonzero, _ = await run(job("int main(){ return 3; }", one))
    assert nonzero.verdicts[0].code == "RE"
    loop, _ = await run(job("int main(){ volatile unsigned long long x = 0; for(;;) x++; }", one, tl=500))
    assert loop.verdicts[0].code == "TLE"
    big, _ = await run(job("#include <vector>\n#include <cstdio>\nint main(){ std::vector<int> v(400000000, 1); printf(\"%d\", v[123]); }", one, mem=64))
    assert big.verdicts[0].code == "MLE"


@needs_gxx
async def test_output_limit() -> None:
    res, _ = await run(job("#include <cstdio>\nint main(){ for(long i=0;i<100000000;i++) puts(\"spam spam spam\"); }", [TestCase(0, "", "x", False)]))
    assert res.verdicts[0].code == "OLE"


@needs_gxx
async def test_deep_recursion_has_a_big_stack() -> None:
    src = ("#include <bits/stdc++.h>\nusing namespace std;\nlong long f(int n){ return n==0?0:n+f(n-1); }\n"
           "int main(){ int n; cin>>n; cout<<f(n)<<endl; }")
    res, _ = await run(job(src, [TestCase(0, "1000000\n", "500000500000", False)], mem=256))
    assert res.verdicts[0].code == "AC", res.verdicts


@needs_gxx
async def test_custom_input_run_shows_stdout() -> None:
    res, _ = await run(job(SUM, [TestCase(0, "40 2\n", None, True)], mode="custom"))
    assert res.verdicts[0].code == "OK" and res.verdicts[0].stdout_tail == "42\n"


async def test_a_missing_compiler_is_a_system_error_not_a_compile_error() -> None:
    j = job(SUM)
    j = replace(j, compile_argv=["no-such-compiler-xyz", *j.compile_argv[1:]])  # type: ignore[index]
    res, _ = await run(j)
    assert res.system_error and "no-such-compiler-xyz" in (res.system_message or "") and res.compile_error is None


def test_language_availability_follows_the_runner() -> None:
    present = language_tools_present(CFG, "subprocess")
    assert present["python"] is True and present["cpp"] is (shutil.which("g++") is not None)
    assert all(language_tools_present(CFG, "docker").values())  # the image brings its own compiler


def test_cpp_tripwire_is_only_a_tripwire() -> None:
    assert cpp_tripwire('#include <cstdlib>\nint main(){ system("ls"); }')
    assert cpp_tripwire("#include <unistd.h>\nint main(){}")
    assert cpp_tripwire("int main(){ fork(); }")
    assert cpp_tripwire(SUM) is None
    assert cpp_tripwire("// system(\"x\") in a comment is fine\nint main(){}") is None
    assert cpp_tripwire("int main(){ int systematic(3); }") is None


async def test_fake_runner_reads_cpp_comments() -> None:
    fake = FakeRunner("test")
    res = await fake.run(job("// VERDICT: WA 2\n// DELAY_MS: 1\nint main(){}"), _noop)
    assert [v.code for v in res.verdicts] == ["AC", "WA"]
    ce = await fake.run(job("// VERDICT: CE\nint main(){}"), _noop)
    assert ce.compile_error


async def _noop(_v: TestVerdict) -> None:
    return None
