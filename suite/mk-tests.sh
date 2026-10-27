#!/bin/bash
# Builds the graded test suite under ~/orch-tests: spec/<t>/{task,check,files}.txt, work/<t> (git repo), ref/<t> (reference solution).
set -e
B=${ORCH_B:-~/orch-tests}
rm -rf "$B/spec" "$B/ref"; mkdir -p "$B/spec" "$B/work" "$B/ref" "$B/runs" "$B/results"
for t in t1 t2 t3 t4 t5 t6 t7; do rm -rf "$B/work/$t" 2>/dev/null || true; mkdir -p "$B/spec/$t" "$B/work/$t" "$B/ref/$t"; done
UNTOUCHED='git diff --quiet $(git rev-list --max-parents=0 HEAD) -- tests'

commit() { (cd "$B/work/$1" && git init -q -b main && git add -A && git -c user.name=t -c user.email=t@t commit -qm base); }

# ---------------- t1: trivial python function ----------------
cat > $B/work/t1/text_utils.py <<'EOF'
def shout(s):
    return s.upper() + "!"
EOF
echo "text_utils.py" > $B/spec/t1/files.txt
cat > $B/spec/t1/task.txt <<'EOF'
Add a function slugify(text) to text_utils.py. It lowercases the text, replaces every run of non-alphanumeric characters with a single hyphen, and strips leading and trailing hyphens. Example: slugify('Hello, World!') returns 'hello-world'. Do not change shout().
EOF
cat > $B/spec/t1/check.txt <<'EOF'
python -c "from text_utils import slugify as s, shout; assert s('Hello, World!')=='hello-world'; assert s('  A  b--c ')=='a-b-c'; assert s('')==''; assert s('!!!')==''; assert s('x1_y2')=='x1-y2'; assert shout('a')=='A!'"
EOF
cat > $B/ref/t1/text_utils.py <<'EOF'
import re


def shout(s):
    return s.upper() + "!"


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
EOF
commit t1

# ---------------- t2: easy powershell ----------------
cat > $B/work/t2/Util.ps1 <<'EOF'
function Get-Timestamp {
    Get-Date -Format "yyyy-MM-dd HH:mm:ss"
}
EOF
echo "Util.ps1" > $B/spec/t2/files.txt
cat > $B/spec/t2/task.txt <<'EOF'
Add a function Format-FileSize to Util.ps1 taking a [long]$Bytes parameter and returning a human-readable string using 1024-based units. Values under 1024 return '<n> B' (for example '512 B'). Larger values use KB, MB or GB with exactly one decimal place (1536 returns '1.5 KB', 1048576 returns '1.0 MB'). Keep the existing Get-Timestamp function.
EOF
cat > $B/spec/t2/check.txt <<'EOF'
pwsh -NoProfile -Command '. ./Util.ps1; $cases = @(@(0,"0 B"),@(512,"512 B"),@(1023,"1023 B"),@(1536,"1.5 KB"),@(1048576,"1.0 MB"),@(5368709120,"5.0 GB")); $bad = 0; foreach ($c in $cases) { $r = Format-FileSize -Bytes $c[0]; if ($r -cne $c[1]) { "FAIL $($c[0]) -> [$r] expected [$($c[1])]"; $bad++ } }; if (-not (Get-Timestamp)) { "Get-Timestamp broken"; $bad++ }; exit $bad'
EOF
cat > $B/ref/t2/Util.ps1 <<'EOF'
function Get-Timestamp {
    Get-Date -Format "yyyy-MM-dd HH:mm:ss"
}

function Format-FileSize {
    param([long]$Bytes)
    if ($Bytes -lt 1024) { return "$Bytes B" }
    $units = 'KB', 'MB', 'GB', 'TB'
    $v = [double]$Bytes
    $i = -1
    do { $v /= 1024; $i++ } while ($v -ge 1024 -and $i -lt 3)
    '{0:F1} {1}' -f $v, $units[$i]
}
EOF
commit t2

# ---------------- t3: fix bugs against existing tests ----------------
mkdir -p $B/work/t3/tests; : > $B/work/t3/conftest.py
cat > $B/work/t3/paginate.py <<'EOF'
def paginate(items, page, size):
    """Return the items on a 1-based page."""
    start = page * size
    end = start + size
    return items[start:end]


def page_count(total, size):
    """Number of pages needed for `total` items."""
    return total // size
EOF
cat > $B/work/t3/tests/test_paginate.py <<'EOF'
import pytest
from paginate import paginate, page_count


def test_first_page():
    assert paginate(list(range(10)), 1, 3) == [0, 1, 2]


def test_last_partial_page():
    assert paginate(list(range(10)), 4, 3) == [9]


def test_page_past_end_is_empty():
    assert paginate(list(range(10)), 5, 3) == []


def test_page_count_rounds_up():
    assert page_count(10, 3) == 4
    assert page_count(9, 3) == 3
    assert page_count(0, 3) == 0


def test_page_zero_invalid():
    with pytest.raises(ValueError):
        paginate([1, 2, 3], 0, 2)


def test_size_must_be_positive():
    with pytest.raises(ValueError):
        paginate([1, 2, 3], 1, 0)
    with pytest.raises(ValueError):
        page_count(5, -1)
EOF
echo "paginate.py tests/test_paginate.py" > $B/spec/t3/files.txt
cat > $B/spec/t3/task.txt <<'EOF'
paginate.py has bugs. Fix them so every test in tests/test_paginate.py passes. Do not modify the tests.
EOF
printf '%s\n%s\n' "python -m pytest -q" "$UNTOUCHED" > $B/spec/t3/check.txt
cat > $B/ref/t3/paginate.py <<'EOF'
def paginate(items, page, size):
    """Return the items on a 1-based page."""
    if page < 1 or size < 1:
        raise ValueError("page and size must be >= 1")
    start = (page - 1) * size
    return items[start:start + size]


def page_count(total, size):
    """Number of pages needed for `total` items."""
    if size < 1:
        raise ValueError("size must be >= 1")
    return -(-total // size)
EOF
commit t3

# ---------------- t4: new modules + CLI, output compared ----------------
printf 'the cat and the hat and the bat\n' > $B/work/t4/sample.txt
printf 'the 3\nand 2\nbat 1\n' > $B/work/t4/expected.txt
printf '# wordstats\n' > $B/work/t4/README.md
: > $B/spec/t4/files.txt
cat > $B/spec/t4/task.txt <<'EOF'
Create textstats.py with a function top_words(text, n) that returns a list of (word, count) tuples for the n most frequent words, case-insensitive, where a word is a run of letters or apostrophes. Sort by count descending, then word ascending. Also create cli.py using argparse so that `python cli.py FILE --top N` reads FILE and prints one line per result in the form '<word> <count>'.
EOF
cat > $B/spec/t4/check.txt <<'EOF'
python cli.py sample.txt --top 3 | diff - expected.txt
python -c "from textstats import top_words as t; assert t('A a b', 1)==[('a',2)]; assert t(\"Don't don't x\", 2)==[(\"don't\",2),('x',1)]; assert t('', 3)==[]"
EOF
cat > $B/ref/t4/textstats.py <<'EOF'
import re
from collections import Counter


def top_words(text, n):
    counts = Counter(re.findall(r"[a-z']+", text.lower()))
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
EOF
cat > $B/ref/t4/cli.py <<'EOF'
import argparse

from textstats import top_words

p = argparse.ArgumentParser()
p.add_argument("file")
p.add_argument("--top", type=int, default=10)
a = p.parse_args()
with open(a.file, encoding="utf-8") as f:
    for word, count in top_words(f.read(), a.top):
        print(f"{word} {count}")
EOF
commit t4

# ---------------- t5: algorithmic class against tests ----------------
mkdir -p $B/work/t5/tests; : > $B/work/t5/conftest.py
cat > $B/work/t5/cache.py <<'EOF'
import time


class TTLCache:
    """LRU cache whose entries also expire.

    TTLCache(capacity, ttl, clock=time.monotonic)
      - capacity: max live entries (>= 1, else ValueError)
      - ttl: seconds an entry lives, measured from the last put() of that key
      - clock: zero-argument callable returning the current time

    get(key) -> value or None. An entry is expired when clock() - stored_at >= ttl.
        A hit marks the key most recently used but does NOT extend its ttl.
    put(key, value): stores/overwrites, resets ttl, marks most recently used.
        If the cache would exceed capacity, evict the least recently used LIVE entry.
        Expired entries never count toward capacity.
    __len__: number of live (non-expired) entries.
    """

    def __init__(self, capacity, ttl, clock=time.monotonic):
        raise NotImplementedError

    def get(self, key):
        raise NotImplementedError

    def put(self, key, value):
        raise NotImplementedError

    def __len__(self):
        raise NotImplementedError
EOF
cat > $B/work/t5/tests/test_cache.py <<'EOF'
import pytest
from cache import TTLCache


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(cap=2, ttl=10):
    c = Clock()
    return TTLCache(cap, ttl, clock=c), c


def test_put_get():
    c, _ = make()
    c.put("a", 1)
    assert c.get("a") == 1


def test_miss_returns_none():
    c, _ = make()
    assert c.get("nope") is None


def test_expiry_boundary():
    c, clk = make(ttl=10)
    c.put("a", 1)
    clk.t = 9.9
    assert c.get("a") == 1
    clk.t = 10
    assert c.get("a") is None


def test_lru_eviction():
    c, _ = make(cap=2)
    c.put("a", 1)
    c.put("b", 2)
    c.get("a")
    c.put("c", 3)
    assert c.get("b") is None
    assert c.get("a") == 1 and c.get("c") == 3


def test_put_overwrites_and_resets_ttl():
    c, clk = make(ttl=10)
    c.put("a", 1)
    clk.t = 6
    c.put("a", 2)
    clk.t = 12
    assert c.get("a") == 2


def test_get_does_not_refresh_ttl():
    c, clk = make(ttl=10)
    c.put("a", 1)
    clk.t = 5
    assert c.get("a") == 1
    clk.t = 10
    assert c.get("a") is None


def test_len_ignores_expired():
    c, clk = make()
    c.put("a", 1)
    c.put("b", 2)
    clk.t = 11
    assert len(c) == 0


def test_expired_entries_do_not_count_toward_capacity():
    c, clk = make(cap=2, ttl=10)
    c.put("a", 1)
    c.put("b", 2)
    clk.t = 11
    c.put("c", 3)
    c.put("d", 4)
    assert c.get("c") == 3 and c.get("d") == 4


def test_invalid_capacity():
    with pytest.raises(ValueError):
        TTLCache(0, 5)
EOF
echo "cache.py tests/test_cache.py" > $B/spec/t5/files.txt
cat > $B/spec/t5/task.txt <<'EOF'
Implement the TTLCache class in cache.py exactly as its docstring describes so that every test in tests/test_cache.py passes. Do not modify the tests.
EOF
printf '%s\n%s\n' "python -m pytest -q" "$UNTOUCHED" > $B/spec/t5/check.txt
cat > $B/ref/t5/cache.py <<'EOF'
import time
from collections import OrderedDict


class TTLCache:
    def __init__(self, capacity, ttl, clock=time.monotonic):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity, self.ttl, self.clock = capacity, ttl, clock
        self._d = OrderedDict()  # key -> (value, stored_at)

    def _purge(self):
        now = self.clock()
        for k in [k for k, (_, t) in self._d.items() if now - t >= self.ttl]:
            del self._d[k]

    def get(self, key):
        self._purge()
        if key not in self._d:
            return None
        self._d.move_to_end(key)
        return self._d[key][0]

    def put(self, key, value):
        self._purge()
        self._d[key] = (value, self.clock())
        self._d.move_to_end(key)
        while len(self._d) > self.capacity:
            self._d.popitem(last=False)

    def __len__(self):
        self._purge()
        return len(self._d)
EOF
commit t5

# ---------------- t6: powershell + Pester ----------------
cat > $B/work/t6/Invoke-Retry.ps1 <<'EOF'
function Invoke-Retry {
    # TODO: implement. See Invoke-Retry.Tests.ps1 for the required behaviour.
    param()
}
EOF
cat > $B/work/t6/Invoke-Retry.Tests.ps1 <<'EOF'
BeforeAll {
    . $PSScriptRoot/Invoke-Retry.ps1
}

Describe 'Invoke-Retry' {
    It 'returns output on first success' {
        Invoke-Retry -ScriptBlock { 42 } | Should -Be 42
    }
    It 'retries until success' {
        $script:n = 0
        $r = Invoke-Retry -MaxAttempts 3 -ScriptBlock { $script:n++; if ($script:n -lt 3) { throw 'fail' }; 'ok' }
        $r | Should -Be 'ok'
        $script:n | Should -Be 3
    }
    It 'rethrows the last error after MaxAttempts' {
        $script:n = 0
        { Invoke-Retry -MaxAttempts 2 -ScriptBlock { $script:n++; throw 'boom' } } | Should -Throw 'boom'
        $script:n | Should -Be 2
    }
    It 'calls OnRetry with the failed attempt number between attempts' {
        $script:seen = @()
        $script:n = 0
        Invoke-Retry -MaxAttempts 3 -OnRetry { param($a) $script:seen += $a } -ScriptBlock { $script:n++; if ($script:n -lt 3) { throw 'x' }; 'ok' } | Out-Null
        $script:seen | Should -Be @(1, 2)
    }
    It 'rejects MaxAttempts below 1' {
        { Invoke-Retry -MaxAttempts 0 -ScriptBlock { 1 } } | Should -Throw
    }
}
EOF
echo "Invoke-Retry.ps1 Invoke-Retry.Tests.ps1" > $B/spec/t6/files.txt
cat > $B/spec/t6/task.txt <<'EOF'
Implement the Invoke-Retry function in Invoke-Retry.ps1 so that every test in Invoke-Retry.Tests.ps1 passes. Parameters: -ScriptBlock (mandatory), -MaxAttempts (int, default 3, must be at least 1, enforced with ValidateRange), -DelaySeconds (int, default 0, sleep between attempts), -OnRetry (optional script block called with the failed attempt number before the next attempt). Do not modify the test file.
EOF
cat > $B/spec/t6/check.txt <<'EOF'
pwsh -NoProfile -Command "Invoke-Pester -Path ./Invoke-Retry.Tests.ps1 -CI -Output Minimal"
git diff --quiet $(git rev-list --max-parents=0 HEAD) -- Invoke-Retry.Tests.ps1
EOF
cat > $B/ref/t6/Invoke-Retry.ps1 <<'EOF'
function Invoke-Retry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][scriptblock]$ScriptBlock,
        [ValidateRange(1, [int]::MaxValue)][int]$MaxAttempts = 3,
        [int]$DelaySeconds = 0,
        [scriptblock]$OnRetry
    )
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            return & $ScriptBlock
        }
        catch {
            if ($attempt -ge $MaxAttempts) { throw }
            if ($OnRetry) { & $OnRetry $attempt }
            if ($DelaySeconds -gt 0) { Start-Sleep -Seconds $DelaySeconds }
        }
    }
}
EOF
commit t6

# ---------------- t7: multi-file feature, old tests must keep passing ----------------
mkdir -p $B/work/t7/tests; : > $B/work/t7/conftest.py
cat > $B/work/t7/models.py <<'EOF'
from dataclasses import dataclass


@dataclass
class Item:
    name: str
    price: float
    qty: int = 1

    def total(self):
        return self.price * self.qty
EOF
cat > $B/work/t7/store.py <<'EOF'
class Cart:
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)

    def total(self):
        return sum(i.total() for i in self.items)
EOF
cat > $B/work/t7/cli.py <<'EOF'
import sys

from models import Item
from store import Cart


def main(argv):
    cart = Cart()
    for spec in argv:
        name, price, qty = spec.split(":")
        cart.add(Item(name, float(price), int(qty)))
    for i in cart.items:
        print(f"{i.name} x{i.qty} = {i.total():.2f}")
    print(f"TOTAL {cart.total():.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
EOF
cat > $B/work/t7/tests/test_cart.py <<'EOF'
from cli import main
from models import Item
from store import Cart


def test_item_total():
    assert Item("a", 2.5, 4).total() == 10.0


def test_cart_total():
    c = Cart()
    c.add(Item("a", 1.0, 2))
    c.add(Item("b", 3.0))
    assert c.total() == 5.0


def test_cli_output(capsys):
    main(["a:2:3", "b:1:1"])
    out = capsys.readouterr().out.splitlines()
    assert out == ["a x3 = 6.00", "b x1 = 1.00", "TOTAL 7.00"]
EOF
cat > $B/work/t7/tests/test_discount.py <<'EOF'
import pytest
from cli import main
from models import Item
from store import Cart


def test_discount_applies_to_item_total():
    assert Item("a", 10, 2, discount_pct=10).total() == 18.0


def test_discount_defaults_to_zero():
    assert Item("a", 10, 2).discount_pct == 0


@pytest.mark.parametrize("bad", [-1, 101])
def test_discount_must_be_0_to_100(bad):
    with pytest.raises(ValueError):
        Item("a", 10, 1, discount_pct=bad)


def test_cart_total_uses_discounts():
    c = Cart()
    c.add(Item("a", 10, 2, discount_pct=10))
    c.add(Item("b", 5, 1))
    assert c.total() == 23.0


def test_cli_optional_fourth_field_is_discount(capsys):
    main(["a:10:2:10", "b:5:1"])
    out = capsys.readouterr().out.splitlines()
    assert out == ["a x2 = 18.00 (-10%)", "b x1 = 5.00", "TOTAL 23.00"]
EOF
echo "models.py store.py cli.py tests/test_cart.py tests/test_discount.py" > $B/spec/t7/files.txt
cat > $B/spec/t7/task.txt <<'EOF'
Add per-item percentage discounts to the cart. Item gets an optional discount_pct field (default 0) that must be between 0 and 100 inclusive, else ValueError at construction. Item.total() applies the discount. In cli.py a spec may have an optional fourth colon-separated field, the discount percent (for example 'a:10:2:10'). When an item has a non-zero discount its output line gets a suffix, for example 'a x2 = 18.00 (-10%)'; items without a discount print exactly as before. Existing tests must keep passing and tests/test_discount.py must pass. Do not modify any tests.
EOF
printf '%s\n%s\n' "python -m pytest -q" "$UNTOUCHED" > $B/spec/t7/check.txt
cat > $B/ref/t7/models.py <<'EOF'
from dataclasses import dataclass


@dataclass
class Item:
    name: str
    price: float
    qty: int = 1
    discount_pct: float = 0

    def __post_init__(self):
        if not 0 <= self.discount_pct <= 100:
            raise ValueError("discount_pct must be between 0 and 100")

    def total(self):
        return self.price * self.qty * (1 - self.discount_pct / 100)
EOF
cat > $B/ref/t7/cli.py <<'EOF'
import sys

from models import Item
from store import Cart


def main(argv):
    cart = Cart()
    for spec in argv:
        parts = spec.split(":")
        name, price, qty = parts[:3]
        disc = float(parts[3]) if len(parts) > 3 else 0
        cart.add(Item(name, float(price), int(qty), disc))
    for i in cart.items:
        suffix = f" (-{i.discount_pct:g}%)" if i.discount_pct else ""
        print(f"{i.name} x{i.qty} = {i.total():.2f}{suffix}")
    print(f"TOTAL {cart.total():.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
EOF
commit t7
echo "suite built: $(ls $B/spec | tr '\n' ' ')"
