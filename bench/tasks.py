"""Coding tasks for bench.py. Each is a prompt plus assert-based tests run against the model's code."""

TASKS = [
    {
        "name": "lru_cache",
        "prompt": """Implement a Python class `LRUCache(capacity: int)` with methods `get(key)` (returns the value or -1 if missing)
and `put(key, value)`. Both must be O(1). When inserting into a full cache, evict the least recently used key.
`get` and `put` both count as a use. `put` on an existing key updates its value. capacity >= 1.""",
        "tests": """
c = LRUCache(2)
c.put(1, 1); c.put(2, 2)
assert c.get(1) == 1
c.put(3, 3)
assert c.get(2) == -1
c.put(4, 4)
assert c.get(1) == -1 and c.get(3) == 3 and c.get(4) == 4
c.put(3, 33)
c.put(5, 5)
assert c.get(4) == -1 and c.get(3) == 33 and c.get(5) == 5
d = LRUCache(1)
d.put("a", 1); d.put("b", 2)
assert d.get("a") == -1 and d.get("b") == 2
""",
    },
    {
        "name": "parse_duration",
        "prompt": """Write a Python function `parse_duration(s: str) -> int` that converts strings like "1h30m", "45s", "2d4h",
"1w", "1h 30m 15s" into a total number of seconds. Units: w (week), d, h, m, s. Whitespace between parts is allowed.
Each unit may appear at most once and units must appear in descending order (w, d, h, m, s).
Raise ValueError for: empty/blank input, unknown units, missing numbers, repeated or out-of-order units, negative numbers,
or any leftover characters.""",
        "tests": """
assert parse_duration("45s") == 45
assert parse_duration("1h30m") == 5400
assert parse_duration("2d4h") == 2*86400 + 4*3600
assert parse_duration("1w") == 604800
assert parse_duration("1h 30m 15s") == 5415
assert parse_duration("0s") == 0
for bad in ["", "   ", "5x", "h", "1h1h", "30m1h", "-5s", "1h30", "1.5h", "abc", "10m 5"]:
    try:
        parse_duration(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"no ValueError for {bad!r}")
""",
    },
    {
        "name": "calc",
        "prompt": """Write a Python function `calc(expr: str) -> float` that evaluates an arithmetic expression with
+, -, *, /, parentheses, unary minus/plus (including repeated, like "--3"), decimal numbers like "3.5" and ".5", and
arbitrary whitespace. Standard precedence; operators of equal precedence are left-associative.
Do NOT use eval, exec, compile or the ast module. Raise ValueError on malformed input: unbalanced parentheses,
dangling operators, empty input or empty parentheses, invalid characters, two numbers in a row ("1 2"), and any
operator not listed above (so "2 ** 3" is malformed). Division by zero raises ZeroDivisionError.""",
        "tests": """
import math
assert math.isclose(calc("1 + 2 * 3"), 7)
assert math.isclose(calc("(1 + 2) * 3"), 9)
assert math.isclose(calc("10 - 4 - 3"), 3)
assert math.isclose(calc("100 / 10 / 5"), 2)
assert math.isclose(calc("-3 + 5"), 2)
assert math.isclose(calc("--3"), 3)
assert math.isclose(calc("2 * -(3 + 1)"), -8)
assert math.isclose(calc(" .5 + 3.25 "), 3.75)
assert math.isclose(calc("((2))"), 2)
assert math.isclose(calc("2*3+4*5-6/2"), 23)
for bad in ["", "1 +", "(1 + 2", "1 + 2)", "2 ** 3", "abc", "1 2", "()"]:
    try:
        calc(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"no ValueError for {bad!r}")
try:
    calc("1 / (2 - 2)")
except ZeroDivisionError:
    pass
else:
    raise AssertionError("no ZeroDivisionError")
""",
    },
    {
        "name": "topo_sort",
        "prompt": """Write a Python function `topo_sort(deps: dict[str, list[str]]) -> list[str]`. `deps[x]` lists the items
that must come BEFORE x. Items that only appear inside the lists are also part of the graph. Return a valid ordering of
all items; whenever several items are available at once, pick the alphabetically smallest first (so the result is
deterministic). If there is a cycle, raise ValueError whose message contains the names of the items in the cycle.""",
        "tests": """
assert topo_sort({}) == []
assert topo_sort({"b": ["a"], "c": ["b"]}) == ["a", "b", "c"]
assert topo_sort({"d": [], "c": [], "b": [], "a": []}) == ["a", "b", "c", "d"]
assert topo_sort({"app": ["lib", "util"], "lib": ["util"], "test": ["app"]}) == ["util", "lib", "app", "test"]
assert topo_sort({"z": ["y"], "b": ["a"]}) == ["a", "b", "y", "z"]
try:
    topo_sort({"a": ["c"], "b": ["a"], "c": ["b"], "d": []})
except ValueError as e:
    m = str(e)
    assert "a" in m and "b" in m and "c" in m, m
else:
    raise AssertionError("cycle not detected")
try:
    topo_sort({"x": ["x"]})
except ValueError:
    pass
else:
    raise AssertionError("self-loop not detected")
""",
    },
    {
        "name": "interval_set",
        "prompt": """Implement a Python class `IntervalSet` that stores a set of integers as sorted, non-overlapping,
non-adjacent half-open ranges [start, end). Methods:
- `add(start, end)`: add the range (merge with overlapping or touching ranges). Ignore empty ranges (start >= end).
- `remove(start, end)`: remove the range, splitting existing ranges if needed.
- `contains(x) -> bool`
- `ranges() -> list[tuple[int, int]]`: current ranges, sorted.
- `__len__`: total count of integers covered.""",
        "tests": """
s = IntervalSet()
s.add(1, 5); s.add(10, 20)
assert s.ranges() == [(1, 5), (10, 20)]
s.add(5, 10)
assert s.ranges() == [(1, 20)]
s.remove(3, 7)
assert s.ranges() == [(1, 3), (7, 20)]
assert len(s) == 2 + 13
assert s.contains(2) and not s.contains(3) and s.contains(7) and not s.contains(20)
s.add(0, 100)
assert s.ranges() == [(0, 100)]
s.remove(0, 100)
assert s.ranges() == [] and len(s) == 0
s.add(5, 5)
assert s.ranges() == []
s.add(1, 3); s.add(7, 9); s.add(4, 6)
s.remove(2, 8)
assert s.ranges() == [(1, 2), (8, 9)], s.ranges()
""",
    },
]
