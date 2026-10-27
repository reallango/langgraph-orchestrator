#!/bin/bash
# Builds ~/orch-bench/corpus/<t>/{base/,ref/,hidden/,task.txt,check.txt,edit.txt,hidden.txt,meta.txt}
set -e
C=${CORPUS:-$HOME/orch-bench/corpus}
rm -rf "$C"; mkdir -p "$C"
UNT='git diff --quiet $(git rev-list --max-parents=0 HEAD) --'
PESTER() { echo "pwsh -NoProfile -Command \"Invoke-Pester -Path ./$1 -CI -Output Minimal\""; }
mk() { mkdir -p "$C/$1/base" "$C/$1/ref" "$C/$1/hidden"; echo "$2 $3" > "$C/$1/meta.txt"; }   # lang tier

# ============ t1  py T1: slugify ============
mk t1 py T1
cat > $C/t1/base/text_utils.py <<'EOF'
def shout(s):
    return s.upper() + "!"
EOF
echo "text_utils.py" > $C/t1/edit.txt
echo "Add a function slugify(text) to text_utils.py. It lowercases the text, replaces every run of non-alphanumeric characters with a single hyphen, and strips leading and trailing hyphens. Example: slugify('Hello, World!') returns 'hello-world'. Do not change shout()." > $C/t1/task.txt
cat > $C/t1/check.txt <<'EOF'
python -c "from text_utils import slugify as s, shout; assert s('Hello, World!')=='hello-world'; assert s('  A  b--c ')=='a-b-c'; assert s('')==''; assert s('!!!')==''; assert s('x1_y2')=='x1-y2'; assert shout('a')=='A!'"
EOF
cat > $C/t1/ref/text_utils.py <<'EOF'
import re


def shout(s):
    return s.upper() + "!"


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
EOF
cat > $C/t1/hidden/hidden_test.py <<'EOF'
from text_utils import shout, slugify


def test_cases():
    assert slugify("Hello World") == "hello-world"
    assert slugify("  multiple   spaces  ") == "multiple-spaces"
    assert slugify("Already-slugged") == "already-slugged"
    assert slugify("a/b\\c") == "a-b-c"
    assert slugify("123 go!") == "123-go"
    assert slugify("---") == ""
    assert slugify("UPPER_case.Mixed") == "upper-case-mixed"


def test_shout_untouched():
    assert shout("hi") == "HI!"
EOF
echo "python -m pytest -q -p no:cacheprovider hidden_test.py" > $C/t1/hidden.txt

# ============ t2  ps T1: Format-FileSize ============
mk t2 ps T1
cat > $C/t2/base/Util.ps1 <<'EOF'
function Get-Timestamp {
    Get-Date -Format "yyyy-MM-dd HH:mm:ss"
}
EOF
echo "Util.ps1" > $C/t2/edit.txt
echo "Add a function Format-FileSize to Util.ps1 taking a [long]\$Bytes parameter and returning a human-readable string using 1024-based units. Values under 1024 return '<n> B' (for example '512 B'). Larger values use KB, MB or GB with exactly one decimal place (1536 returns '1.5 KB', 1048576 returns '1.0 MB'). Keep the existing Get-Timestamp function." | sed 's/\\\$/$/' > $C/t2/task.txt
cat > $C/t2/check.txt <<'EOF'
pwsh -NoProfile -Command '. ./Util.ps1; $cases = @(@(0,"0 B"),@(512,"512 B"),@(1023,"1023 B"),@(1536,"1.5 KB"),@(1048576,"1.0 MB"),@(5368709120,"5.0 GB")); $bad = 0; foreach ($c in $cases) { $r = Format-FileSize -Bytes $c[0]; if ($r -cne $c[1]) { "FAIL $($c[0]) -> [$r] expected [$($c[1])]"; $bad++ } }; if (-not (Get-Timestamp)) { "Get-Timestamp broken"; $bad++ }; exit $bad'
EOF
cat > $C/t2/ref/Util.ps1 <<'EOF'
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
cat > $C/t2/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll { . $PSScriptRoot/Util.ps1 }
Describe 'Format-FileSize hidden' {
    It 'formats sizes' {
        $cases = @(@(1,'1 B'), @(999,'999 B'), @(1024,'1.0 KB'), @(2048,'2.0 KB'), @(10240,'10.0 KB'), @(1572864,'1.5 MB'), @(1610612736,'1.5 GB'))
        foreach ($c in $cases) { Format-FileSize -Bytes $c[0] | Should -BeExactly $c[1] }
    }
    It 'keeps Get-Timestamp' { Get-Timestamp | Should -Match '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$' }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t2/hidden.txt

# ============ t3  py T2: paginate bugfix ============
mk t3 py T2
mkdir -p $C/t3/base/tests; : > $C/t3/base/conftest.py
cat > $C/t3/base/paginate.py <<'EOF'
def paginate(items, page, size):
    """Return the items on a 1-based page."""
    start = page * size
    end = start + size
    return items[start:end]


def page_count(total, size):
    """Number of pages needed for `total` items."""
    return total // size
EOF
cat > $C/t3/base/tests/test_paginate.py <<'EOF'
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
echo "paginate.py tests/test_paginate.py" > $C/t3/edit.txt
echo "paginate.py has bugs. Fix them so every test in tests/test_paginate.py passes. Do not modify the tests." > $C/t3/task.txt
printf '%s\n%s\n' "python -m pytest -q -p no:cacheprovider" "$UNT tests" > $C/t3/check.txt
cat > $C/t3/ref/paginate.py <<'EOF'
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
mkdir -p $C/t3/hidden/tests
cat > $C/t3/hidden/tests/test_hidden.py <<'EOF'
import pytest
from paginate import paginate, page_count


def test_more_pages():
    assert paginate(list("abcdef"), 2, 2) == ["c", "d"]
    assert paginate([], 1, 5) == []
    assert paginate([1, 2], 1, 10) == [1, 2]


def test_counts():
    assert page_count(1, 1) == 1
    assert page_count(7, 7) == 1
    assert page_count(8, 7) == 2
    assert page_count(100, 10) == 10


def test_negative_page():
    with pytest.raises(ValueError):
        paginate([1], -1, 2)


def test_does_not_mutate():
    data = [1, 2, 3, 4]
    paginate(data, 1, 2)
    assert data == [1, 2, 3, 4]
EOF
echo "python -m pytest -q -p no:cacheprovider tests/test_hidden.py" > $C/t3/hidden.txt

# ============ t4  py T3: textstats + cli ============
mk t4 py T3
printf 'the cat and the hat and the bat\n' > $C/t4/base/sample.txt
printf 'the 3\nand 2\nbat 1\n' > $C/t4/base/expected.txt
printf '# wordstats\n' > $C/t4/base/README.md
: > $C/t4/edit.txt
echo "Create textstats.py with a function top_words(text, n) that returns a list of (word, count) tuples for the n most frequent words, case-insensitive, where a word is a run of letters or apostrophes. Sort by count descending, then word ascending. Also create cli.py using argparse so that \`python cli.py FILE --top N\` reads FILE and prints one line per result in the form '<word> <count>'." | sed 's/\\`/`/g' > $C/t4/task.txt
cat > $C/t4/check.txt <<'EOF'
python cli.py sample.txt --top 3 | diff - expected.txt
python -c "from textstats import top_words as t; assert t('A a b', 1)==[('a',2)]; assert t(\"Don't don't x\", 2)==[(\"don't\",2),('x',1)]; assert t('', 3)==[]"
EOF
cat > $C/t4/ref/textstats.py <<'EOF'
import re
from collections import Counter


def top_words(text, n):
    counts = Counter(re.findall(r"[a-z']+", text.lower()))
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
EOF
cat > $C/t4/ref/cli.py <<'EOF'
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
cat > $C/t4/hidden/hidden_test.py <<'EOF'
import os
import subprocess
import sys

from textstats import top_words


def test_case_and_ties():
    assert top_words("The the THE cat", 2) == [("the", 3), ("cat", 1)]
    assert top_words("b a b a c", 3) == [("a", 2), ("b", 2), ("c", 1)]


def test_punctuation_and_zero():
    assert top_words("Hello, world! Hello.", 1) == [("hello", 2)]
    assert top_words("x y", 0) == []


def test_cli(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("b a b a c")
    out = subprocess.run([sys.executable, "cli.py", str(f), "--top", "2"], capture_output=True, text=True, cwd=os.getcwd())
    assert out.stdout.splitlines() == ["a 2", "b 2"]
EOF
echo "python -m pytest -q -p no:cacheprovider hidden_test.py" > $C/t4/hidden.txt

# ============ t5  py T3: TTLCache ============
mk t5 py T3
mkdir -p $C/t5/base/tests; : > $C/t5/base/conftest.py
cat > $C/t5/base/cache.py <<'EOF'
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
cat > $C/t5/base/tests/test_cache.py <<'EOF'
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
echo "cache.py tests/test_cache.py" > $C/t5/edit.txt
echo "Implement the TTLCache class in cache.py exactly as its docstring describes so that every test in tests/test_cache.py passes. Do not modify the tests." > $C/t5/task.txt
printf '%s\n%s\n' "python -m pytest -q -p no:cacheprovider" "$UNT tests" > $C/t5/check.txt
cat > $C/t5/ref/cache.py <<'EOF'
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
mkdir -p $C/t5/hidden/tests
cat > $C/t5/hidden/tests/test_hidden.py <<'EOF'
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


def test_overwrite_refreshes_recency():
    c, _ = make(cap=2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("a", 10)
    c.put("c", 3)
    assert c.get("b") is None
    assert c.get("a") == 10


def test_overwrite_does_not_grow():
    c, _ = make(cap=3)
    c.put("a", 1)
    c.put("a", 2)
    c.put("a", 3)
    assert len(c) == 1


def test_eviction_skips_expired_and_removes_lru_live():
    c, clk = make(cap=2, ttl=10)
    c.put("a", 1)
    clk.t = 5
    c.put("b", 2)
    clk.t = 11          # a expired, b live
    c.put("c", 3)       # fits: a is dead
    assert len(c) == 2
    assert c.get("b") == 2 and c.get("c") == 3


def test_get_marks_recent_but_not_ttl():
    c, clk = make(cap=2, ttl=10)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1
    c.put("c", 3)
    assert c.get("b") is None and c.get("a") == 1
    clk.t = 10
    assert c.get("a") is None


def test_negative_capacity():
    with pytest.raises(ValueError):
        TTLCache(-1, 5)


def test_none_value_roundtrip_len():
    c, _ = make()
    c.put("k", 0)
    assert c.get("k") == 0
    assert len(c) == 1
EOF
echo "python -m pytest -q -p no:cacheprovider tests/test_hidden.py" > $C/t5/hidden.txt

# ============ t6  ps T3: Invoke-Retry (Pester) ============
mk t6 ps T3
cat > $C/t6/base/Invoke-Retry.ps1 <<'EOF'
function Invoke-Retry {
    # TODO: implement. See Invoke-Retry.Tests.ps1 for the required behaviour.
    param()
}
EOF
cat > $C/t6/base/Invoke-Retry.Tests.ps1 <<'EOF'
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
echo "Invoke-Retry.ps1 Invoke-Retry.Tests.ps1" > $C/t6/edit.txt
echo "Implement the Invoke-Retry function in Invoke-Retry.ps1 so that every test in Invoke-Retry.Tests.ps1 passes. Parameters: -ScriptBlock (mandatory), -MaxAttempts (int, default 3, must be at least 1, enforced with ValidateRange), -DelaySeconds (int, default 0, sleep between attempts), -OnRetry (optional script block called with the failed attempt number before the next attempt). Do not modify the test file." > $C/t6/task.txt
printf '%s\n%s\n' "$(PESTER Invoke-Retry.Tests.ps1)" "$UNT Invoke-Retry.Tests.ps1" > $C/t6/check.txt
cat > $C/t6/ref/Invoke-Retry.ps1 <<'EOF'
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
cat > $C/t6/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll { . $PSScriptRoot/Invoke-Retry.ps1 }
Describe 'Invoke-Retry hidden' {
    It 'defaults to 3 attempts' {
        $script:n = 0
        { Invoke-Retry -ScriptBlock { $script:n++; throw 'x' } } | Should -Throw
        $script:n | Should -Be 3
    }
    It 'MaxAttempts 1 throws without OnRetry' {
        $script:c = 0
        { Invoke-Retry -MaxAttempts 1 -OnRetry { $script:c++ } -ScriptBlock { throw 'once' } } | Should -Throw 'once'
        $script:c | Should -Be 0
    }
    It 'does not call OnRetry on success' {
        $script:c = 0
        Invoke-Retry -OnRetry { $script:c++ } -ScriptBlock { 1 } | Out-Null
        $script:c | Should -Be 0
    }
    It 'returns all output objects' {
        @(Invoke-Retry -ScriptBlock { 1; 2; 3 }).Count | Should -Be 3
    }
    It 'rejects negative MaxAttempts' {
        { Invoke-Retry -MaxAttempts -1 -ScriptBlock { 1 } } | Should -Throw
    }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t6/hidden.txt

# ============ t7  py T4: discounts across 3 files ============
mk t7 py T4
mkdir -p $C/t7/base/tests; : > $C/t7/base/conftest.py
cat > $C/t7/base/models.py <<'EOF'
from dataclasses import dataclass


@dataclass
class Item:
    name: str
    price: float
    qty: int = 1

    def total(self):
        return self.price * self.qty
EOF
cat > $C/t7/base/store.py <<'EOF'
class Cart:
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)

    def total(self):
        return sum(i.total() for i in self.items)
EOF
cat > $C/t7/base/cli.py <<'EOF'
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
cat > $C/t7/base/tests/test_cart.py <<'EOF'
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
cat > $C/t7/base/tests/test_discount.py <<'EOF'
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
echo "models.py store.py cli.py tests/test_cart.py tests/test_discount.py" > $C/t7/edit.txt
echo "Add per-item percentage discounts to the cart. Item gets an optional discount_pct field (default 0) that must be between 0 and 100 inclusive, else ValueError at construction. Item.total() applies the discount. In cli.py a spec may have an optional fourth colon-separated field, the discount percent (for example 'a:10:2:10'). When an item has a non-zero discount its output line gets a suffix, for example 'a x2 = 18.00 (-10%)'; items without a discount print exactly as before. Existing tests must keep passing and tests/test_discount.py must pass. Do not modify any tests." > $C/t7/task.txt
printf '%s\n%s\n' "python -m pytest -q -p no:cacheprovider" "$UNT tests" > $C/t7/check.txt
cat > $C/t7/ref/models.py <<'EOF'
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
cat > $C/t7/ref/cli.py <<'EOF'
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
mkdir -p $C/t7/hidden/tests
cat > $C/t7/hidden/tests/test_hidden.py <<'EOF'
import pytest
from cli import main
from models import Item
from store import Cart


def test_full_and_zero_discount_boundaries():
    assert Item("a", 10, 1, discount_pct=100).total() == 0
    assert Item("a", 10, 1, discount_pct=0).total() == 10


def test_discount_with_quantity():
    assert Item("a", 10, 3, discount_pct=50).total() == 15.0


def test_cart_with_two_discounted_items():
    c = Cart()
    c.add(Item("a", 100, 1, discount_pct=10))
    c.add(Item("b", 50, 2, discount_pct=20))
    assert c.total() == pytest.approx(170.0)


def test_cli_full_discount(capsys):
    main(["a:10:1:100"])
    out = capsys.readouterr().out.splitlines()
    assert out == ["a x1 = 0.00 (-100%)", "TOTAL 0.00"]


def test_cli_zero_discount_has_no_suffix(capsys):
    main(["a:10:1:0", "b:2:2"])
    out = capsys.readouterr().out.splitlines()
    assert out == ["a x1 = 10.00", "b x2 = 4.00", "TOTAL 14.00"]
EOF
echo "python -m pytest -q -p no:cacheprovider tests/test_hidden.py" > $C/t7/hidden.txt

# ============ t8  ps T1: Format-Duration ============
mk t8 ps T1
cat > $C/t8/base/Time.ps1 <<'EOF'
function Get-Now {
    Get-Date
}
EOF
echo "Time.ps1" > $C/t8/edit.txt
echo "Add a function Format-Duration to Time.ps1 taking a mandatory [int]\$Seconds parameter and returning a string. Under 60 seconds it returns '<s>s' (for example '5s'). From 60 seconds up to an hour it returns '<m>m <ss>s' with seconds zero-padded to two digits (for example '2m 05s'). From one hour up it returns '<h>h <mm>m <ss>s' with minutes and seconds zero-padded (for example '1h 02m 03s'); hours are not rolled into days, so 90000 seconds is '25h 00m 00s'. Negative values must be rejected by parameter validation. Keep Get-Now." | sed 's/\\\$/$/' > $C/t8/task.txt
cat > $C/t8/check.txt <<'EOF'
pwsh -NoProfile -Command '. ./Time.ps1; $cases = @(@(0,"0s"),@(59,"59s"),@(60,"1m 00s"),@(125,"2m 05s"),@(3600,"1h 00m 00s"),@(3723,"1h 02m 03s")); $bad = 0; foreach ($c in $cases) { $r = Format-Duration -Seconds $c[0]; if ($r -cne $c[1]) { "FAIL $($c[0]) -> [$r] expected [$($c[1])]"; $bad++ } }; exit $bad'
EOF
cat > $C/t8/ref/Time.ps1 <<'EOF'
function Get-Now {
    Get-Date
}

function Format-Duration {
    param([Parameter(Mandatory)][ValidateRange(0, [int]::MaxValue)][int]$Seconds)
    $h = [math]::Floor($Seconds / 3600)
    $m = [math]::Floor(($Seconds % 3600) / 60)
    $s = $Seconds % 60
    if ($h -gt 0) { '{0}h {1:00}m {2:00}s' -f $h, $m, $s }
    elseif ($m -gt 0) { '{0}m {1:00}s' -f $m, $s }
    else { '{0}s' -f $s }
}
EOF
cat > $C/t8/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll { . $PSScriptRoot/Time.ps1 }
Describe 'Format-Duration hidden' {
    It 'formats edge values' {
        $cases = @(@(1,'1s'), @(61,'1m 01s'), @(3599,'59m 59s'), @(7325,'2h 02m 05s'), @(86400,'24h 00m 00s'), @(90000,'25h 00m 00s'))
        foreach ($c in $cases) { Format-Duration -Seconds $c[0] | Should -BeExactly $c[1] }
    }
    It 'rejects negative seconds' { { Format-Duration -Seconds -1 } | Should -Throw }
    It 'keeps Get-Now' { Get-Now | Should -BeOfType ([datetime]) }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t8/hidden.txt

# ============ t9  ps T2: Merge-Ranges bugfix ============
mk t9 ps T2
cat > $C/t9/base/Ranges.ps1 <<'EOF'
function Merge-Ranges {
    param([object[]]$Ranges)
    if (-not $Ranges) { return @() }
    $result = @()
    $current = $Ranges[0]
    foreach ($r in $Ranges[1..($Ranges.Count - 1)]) {
        if ($r[0] -lt $current[1]) {
            $current = @($current[0], [math]::Max($current[1], $r[1]))
        } else {
            $result += ,$current
            $current = $r
        }
    }
    $result += ,$current
    return $result
}
EOF
cat > $C/t9/base/Ranges.Tests.ps1 <<'EOF'
BeforeAll {
    . $PSScriptRoot/Ranges.ps1
    function Show($r) { (@($r) | ForEach-Object { "$($_[0])-$($_[1])" }) -join ',' }
}

Describe 'Merge-Ranges' {
    It 'merges overlapping ranges' {
        Show (Merge-Ranges -Ranges @(@(1,3), @(2,6), @(8,10))) | Should -Be '1-6,8-10'
    }
    It 'merges touching ranges' {
        Show (Merge-Ranges -Ranges @(@(1,2), @(2,5))) | Should -Be '1-5'
    }
    It 'sorts unsorted input' {
        Show (Merge-Ranges -Ranges @(@(8,10), @(1,3), @(2,6))) | Should -Be '1-6,8-10'
    }
    It 'returns a single range as one pair inside an array' {
        $r = Merge-Ranges -Ranges @(,@(4,9))
        @($r).Count | Should -Be 1
        $r[0][0] | Should -Be 4
        $r[0][1] | Should -Be 9
    }
    It 'returns nothing for empty input' {
        @(Merge-Ranges -Ranges @()).Count | Should -Be 0
    }
}
EOF
echo "Ranges.ps1 Ranges.Tests.ps1" > $C/t9/edit.txt
echo "Merge-Ranges in Ranges.ps1 has bugs. Fix them so every test in Ranges.Tests.ps1 passes. Do not modify the test file. Note the contract the tests expect: the function takes an array of @(start,end) pairs and returns an array of merged pairs (so a single result must still come back as an array containing one pair)." > $C/t9/task.txt
printf '%s\n%s\n' "$(PESTER Ranges.Tests.ps1)" "$UNT Ranges.Tests.ps1" > $C/t9/check.txt
cat > $C/t9/ref/Ranges.ps1 <<'EOF'
function Merge-Ranges {
    param([object[]]$Ranges)
    if (-not $Ranges) { return }
    $sorted = @($Ranges | Sort-Object { $_[0] }, { $_[1] })
    $result = [System.Collections.Generic.List[object]]::new()
    $cur = @($sorted[0][0], $sorted[0][1])
    for ($i = 1; $i -lt $sorted.Count; $i++) {
        $r = $sorted[$i]
        if ($r[0] -le $cur[1]) { $cur[1] = [math]::Max($cur[1], $r[1]) }
        else { $result.Add($cur); $cur = @($r[0], $r[1]) }
    }
    $result.Add($cur)
    return ,$result.ToArray()
}
EOF
cat > $C/t9/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll {
    . $PSScriptRoot/Ranges.ps1
    function Show($r) { (@($r) | ForEach-Object { "$($_[0])-$($_[1])" }) -join ',' }
}
Describe 'Merge-Ranges hidden' {
    It 'handles contained ranges' { Show (Merge-Ranges -Ranges @(@(1,10), @(2,3), @(4,5))) | Should -Be '1-10' }
    It 'handles chains' { Show (Merge-Ranges -Ranges @(@(1,2), @(2,3), @(3,4), @(10,11))) | Should -Be '1-4,10-11' }
    It 'handles duplicates' { Show (Merge-Ranges -Ranges @(@(5,6), @(5,6))) | Should -Be '5-6' }
    It 'handles negatives' { Show (Merge-Ranges -Ranges @(@(-5,-1), @(-3,2), @(5,6))) | Should -Be '-5-2,5-6' }
    It 'keeps disjoint ranges apart' { Show (Merge-Ranges -Ranges @(@(1,2), @(4,5))) | Should -Be '1-2,4-5' }
    It 'does not mutate the input' {
        $in = @(@(1,3), @(2,6))
        $null = Merge-Ranges -Ranges $in
        $in[0][1] | Should -Be 3
    }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t9/hidden.txt

# ============ t10  ps T2: ConvertFrom-Ini bugfix ============
mk t10 ps T2
cat > $C/t10/base/Ini.ps1 <<'EOF'
function ConvertFrom-Ini {
    param([Parameter(Mandatory)][string]$Text)
    $result = @{}
    $section = ''
    foreach ($line in ($Text -split "`n")) {
        if ($line -match '^\[(.+)\]$') {
            $section = $Matches[1]
            $result[$section] = @{}
        } elseif ($line -match '=') {
            $parts = $line -split '='
            $result[$section][$parts[0]] = $parts[1]
        }
    }
    return $result
}
EOF
cat > $C/t10/base/Ini.Tests.ps1 <<'EOF'
BeforeAll { . $PSScriptRoot/Ini.ps1 }

Describe 'ConvertFrom-Ini' {
    It 'parses sections and keys' {
        $r = ConvertFrom-Ini -Text "[a]`nx=1`ny=2`n[b]`nz=3"
        $r['a']['x'] | Should -Be '1'
        $r['a']['y'] | Should -Be '2'
        $r['b']['z'] | Should -Be '3'
    }
    It 'trims whitespace around keys, values and section names' {
        $r = ConvertFrom-Ini -Text "[ s ]`n  key  =  some value  "
        $r['s']['key'] | Should -Be 'some value'
    }
    It 'ignores blank lines and ; or # comments' {
        $r = ConvertFrom-Ini -Text "; top comment`n[a]`n# note`n`nx=1"
        $r['a'].Keys.Count | Should -Be 1
    }
    It 'keeps equals signs inside values' {
        $r = ConvertFrom-Ini -Text "[db]`nconn=Server=x;Port=5"
        $r['db']['conn'] | Should -Be 'Server=x;Port=5'
    }
    It 'puts keys before any section under _global' {
        $r = ConvertFrom-Ini -Text "top=1`n[a]`nx=2"
        $r['_global']['top'] | Should -Be '1'
    }
    It 'handles Windows line endings' {
        $r = ConvertFrom-Ini -Text "[a]`r`nx=1`r`n"
        $r['a']['x'] | Should -Be '1'
    }
}
EOF
echo "Ini.ps1 Ini.Tests.ps1" > $C/t10/edit.txt
echo "ConvertFrom-Ini in Ini.ps1 has bugs. Fix them so every test in Ini.Tests.ps1 passes. Do not modify the test file." > $C/t10/task.txt
printf '%s\n%s\n' "$(PESTER Ini.Tests.ps1)" "$UNT Ini.Tests.ps1" > $C/t10/check.txt
cat > $C/t10/ref/Ini.ps1 <<'EOF'
function ConvertFrom-Ini {
    param([Parameter(Mandatory)][string]$Text)
    $result = @{}
    $section = '_global'
    foreach ($line in ($Text -split "`r?`n")) {
        $l = $line.Trim()
        if ($l -eq '' -or $l.StartsWith(';') -or $l.StartsWith('#')) { continue }
        if ($l -match '^\[(.+)\]$') {
            $section = $Matches[1].Trim()
            if (-not $result.ContainsKey($section)) { $result[$section] = @{} }
            continue
        }
        $i = $l.IndexOf('=')
        if ($i -lt 1) { continue }
        if (-not $result.ContainsKey($section)) { $result[$section] = @{} }
        $result[$section][$l.Substring(0, $i).Trim()] = $l.Substring($i + 1).Trim()
    }
    return $result
}
EOF
cat > $C/t10/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll { . $PSScriptRoot/Ini.ps1 }
Describe 'ConvertFrom-Ini hidden' {
    It 'later duplicate key wins' {
        $r = ConvertFrom-Ini -Text "[a]`nx=1`nx=2"
        $r['a']['x'] | Should -Be '2'
    }
    It 'same section repeated merges' {
        $r = ConvertFrom-Ini -Text "[a]`nx=1`n[b]`ny=2`n[a]`nz=3"
        $r['a']['x'] | Should -Be '1'
        $r['a']['z'] | Should -Be '3'
    }
    It 'empty value is allowed' {
        $r = ConvertFrom-Ini -Text "[a]`nx="
        $r['a']['x'] | Should -Be ''
    }
    It 'inline hash inside value is kept' {
        $r = ConvertFrom-Ini -Text "[a]`ncolor=#ff0000"
        $r['a']['color'] | Should -Be '#ff0000'
    }
    It 'no global section when there are no loose keys' {
        $r = ConvertFrom-Ini -Text "[a]`nx=1"
        $r.ContainsKey('_global') | Should -BeFalse
    }
    It 'empty text gives empty result' {
        (ConvertFrom-Ini -Text "`n`n").Count | Should -Be 0
    }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t10/hidden.txt

# ============ t11  ps T3: New-Logger ============
mk t11 ps T3
cat > $C/t11/base/Logger.ps1 <<'EOF'
# Logging helpers
EOF
cat > $C/t11/base/Logger.Tests.ps1 <<'EOF'
BeforeAll {
    . $PSScriptRoot/Logger.ps1
    $script:f = Join-Path ([IO.Path]::GetTempPath()) ("logger-test-" + [guid]::NewGuid() + ".log")
}
Describe 'New-Logger' {
    AfterEach { Remove-Item $script:f -ErrorAction SilentlyContinue }
    It 'writes all levels by default with an upper-case level tag' {
        $l = New-Logger -Path $script:f
        $l.Info('hello world')
        $l.Warn('careful')
        $l.Error('bad')
        Get-Content $script:f | Should -Be @('[INFO] hello world', '[WARN] careful', '[ERROR] bad')
    }
    It 'filters below the configured level' {
        $l = New-Logger -Path $script:f -Level Warn
        $l.Info('skip me')
        $l.Warn('keep me')
        Get-Content $script:f | Should -Be @('[WARN] keep me')
    }
    It 'counts only lines actually written' {
        $l = New-Logger -Path $script:f -Level Error
        $l.Info('a'); $l.Warn('b'); $l.Error('c')
        $l.Count | Should -Be 1
    }
    It 'rejects an unknown level' {
        { New-Logger -Path $script:f -Level Verbose } | Should -Throw
    }
}
EOF
echo "Logger.ps1 Logger.Tests.ps1" > $C/t11/edit.txt
echo "Implement New-Logger in Logger.ps1 so every test in Logger.Tests.ps1 passes. New-Logger takes -Path (mandatory) and -Level (Info, Warn or Error, default Info, validated) and returns an object with script methods Info(\$message), Warn(\$message) and Error(\$message), plus a Count property of lines written. A method appends '[LEVEL] message' (level upper-case) to the file only when its level is at or above the configured level (Info < Warn < Error). Do not modify the test file." | sed 's/\\\$/$/g' > $C/t11/task.txt
printf '%s\n%s\n' "$(PESTER Logger.Tests.ps1)" "$UNT Logger.Tests.ps1" > $C/t11/check.txt
cat > $C/t11/ref/Logger.ps1 <<'EOF'
function New-Logger {
    param(
        [Parameter(Mandatory)][string]$Path,
        [ValidateSet('Info', 'Warn', 'Error')][string]$Level = 'Info'
    )
    $order = @{ Info = 0; Warn = 1; Error = 2 }
    $logger = [pscustomobject]@{ Path = $Path; Level = $Level; Count = 0 }
    foreach ($name in 'Info', 'Warn', 'Error') {
        $lvl = $name
        $logger | Add-Member -MemberType ScriptMethod -Name $name -Value ({
            param([string]$Message)
            if ($order[$lvl] -ge $order[$this.Level]) {
                Add-Content -Path $this.Path -Value ('[{0}] {1}' -f $lvl.ToUpper(), $Message)
                $this.Count++
            }
        }.GetNewClosure())
    }
    return $logger
}
EOF
cat > $C/t11/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll {
    . $PSScriptRoot/Logger.ps1
    $script:f = Join-Path ([IO.Path]::GetTempPath()) ("logger-hidden-" + [guid]::NewGuid() + ".log")
}
Describe 'New-Logger hidden' {
    AfterEach { Remove-Item $script:f -ErrorAction SilentlyContinue }
    It 'Error level writes only errors' {
        $l = New-Logger -Path $script:f -Level Error
        $l.Info('i'); $l.Warn('w'); $l.Error('e')
        Get-Content $script:f | Should -Be @('[ERROR] e')
    }
    It 'two loggers keep independent levels and counts' {
        $f2 = $script:f + '.2'
        $a = New-Logger -Path $script:f -Level Info
        $b = New-Logger -Path $f2 -Level Error
        $a.Info('x'); $b.Info('x'); $b.Error('y')
        $a.Count | Should -Be 1
        $b.Count | Should -Be 1
        Remove-Item $f2 -ErrorAction SilentlyContinue
    }
    It 'appends to an existing file' {
        Set-Content $script:f 'old'
        $l = New-Logger -Path $script:f
        $l.Info('new')
        Get-Content $script:f | Should -Be @('old', '[INFO] new')
    }
    It 'Level defaults to Info and is exposed' {
        (New-Logger -Path $script:f).Level | Should -Be 'Info'
    }
    It 'requires Path' {
        { New-Logger -Path $null } | Should -Throw
    }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t11/hidden.txt

# ============ t12  ps T3: Compare-Config ============
mk t12 ps T3
cat > $C/t12/base/Config.ps1 <<'EOF'
# Configuration helpers
EOF
cat > $C/t12/base/Config.Tests.ps1 <<'EOF'
BeforeAll { . $PSScriptRoot/Config.ps1 }

Describe 'Compare-Config' {
    It 'reports added, removed and changed keys, sorted' {
        $old = @{ a = 1; b = 2; c = 3 }
        $new = @{ b = 2; c = 4; d = 5; e = 6 }
        $r = Compare-Config -Old $old -New $new
        ($r.Added -join ',') | Should -Be 'd,e'
        ($r.Removed -join ',') | Should -Be 'a'
        ($r.Changed -join ',') | Should -Be 'c'
    }
    It 'returns empty arrays when nothing differs' {
        $r = Compare-Config -Old @{ a = 1 } -New @{ a = 1 }
        @($r.Added).Count | Should -Be 0
        @($r.Removed).Count | Should -Be 0
        @($r.Changed).Count | Should -Be 0
    }
    It 'compares values as strings so 1 equals "1"' {
        $r = Compare-Config -Old @{ a = 1 } -New @{ a = '1' }
        @($r.Changed).Count | Should -Be 0
    }
    It 'handles empty inputs' {
        $r = Compare-Config -Old @{} -New @{ x = 1 }
        ($r.Added -join ',') | Should -Be 'x'
    }
}
EOF
echo "Config.ps1 Config.Tests.ps1" > $C/t12/edit.txt
echo "Implement Compare-Config in Config.ps1 so every test in Config.Tests.ps1 passes. It takes mandatory -Old and -New hashtables and returns an object with three properties, Added (keys only in New), Removed (keys only in Old) and Changed (keys in both whose values differ when compared as strings), each a sorted array of key names. Do not modify the test file." > $C/t12/task.txt
printf '%s\n%s\n' "$(PESTER Config.Tests.ps1)" "$UNT Config.Tests.ps1" > $C/t12/check.txt
cat > $C/t12/ref/Config.ps1 <<'EOF'
function Compare-Config {
    param([Parameter(Mandatory)][hashtable]$Old, [Parameter(Mandatory)][hashtable]$New)
    $added = @($New.Keys | Where-Object { -not $Old.ContainsKey($_) } | Sort-Object)
    $removed = @($Old.Keys | Where-Object { -not $New.ContainsKey($_) } | Sort-Object)
    $changed = @($Old.Keys | Where-Object { $New.ContainsKey($_) -and "$($Old[$_])" -ne "$($New[$_])" } | Sort-Object)
    [pscustomobject]@{ Added = $added; Removed = $removed; Changed = $changed }
}
EOF
cat > $C/t12/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll { . $PSScriptRoot/Config.ps1 }
Describe 'Compare-Config hidden' {
    It 'everything removed' {
        $r = Compare-Config -Old @{ a = 1; b = 2 } -New @{}
        ($r.Removed -join ',') | Should -Be 'a,b'
        @($r.Added).Count | Should -Be 0
    }
    It 'sorts all three lists' {
        $r = Compare-Config -Old @{ z = 1; y = 1; m = 1 } -New @{ z = 2; y = 2; m = 1; q = 1; b = 1 }
        ($r.Changed -join ',') | Should -Be 'y,z'
        ($r.Added -join ',') | Should -Be 'b,q'
    }
    It 'treats null and empty string as different from a value' {
        $r = Compare-Config -Old @{ a = 'x' } -New @{ a = '' }
        ($r.Changed -join ',') | Should -Be 'a'
    }
    It 'single changed key still behaves as an array' {
        $r = Compare-Config -Old @{ a = 1 } -New @{ a = 2 }
        @($r.Changed).Count | Should -Be 1
        $r.Changed.Count | Should -Be 1
    }
    It 'does not modify inputs' {
        $old = @{ a = 1 }; $new = @{ a = 2; b = 3 }
        $null = Compare-Config -Old $old -New $new
        $old.Count | Should -Be 1
        $new.Count | Should -Be 2
    }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t12/hidden.txt

# ============ t13  ps T4: report formats across two files ============
mk t13 ps T4
cat > $C/t13/base/Inventory.ps1 <<'EOF'
function Get-InventoryItems {
    @(
        [pscustomobject]@{ Name = 'bolt'; Qty = 100; Price = 0.25 },
        [pscustomobject]@{ Name = 'nut'; Qty = 250; Price = 0.1 },
        [pscustomobject]@{ Name = 'gear'; Qty = 12; Price = 4.5 }
    )
}
EOF
cat > $C/t13/base/Report.ps1 <<'EOF'
function Format-Report {
    param([Parameter(Mandatory)][object[]]$Items)
    foreach ($i in $Items) { '{0}: {1} @ {2:N2}' -f $i.Name, $i.Qty, $i.Price }
    '{0} items, total value {1:N2}' -f $Items.Count, (($Items | ForEach-Object { $_.Qty * $_.Price } | Measure-Object -Sum).Sum)
}
EOF
cat > $C/t13/base/Inventory.Tests.ps1 <<'EOF'
BeforeAll {
    . $PSScriptRoot/Inventory.ps1
    . $PSScriptRoot/Report.ps1
}

Describe 'existing behaviour' {
    It 'lists three items' { @(Get-InventoryItems).Count | Should -Be 3 }
    It 'text report is the default' {
        $out = @(Format-Report -Items (Get-InventoryItems))
        $out[0] | Should -Be 'bolt: 100 @ 0.25'
        $out[-1] | Should -Be '3 items, total value 104.00'
    }
}

Describe 'MinQty filter' {
    It 'filters on Qty greater than or equal to MinQty' {
        (@(Get-InventoryItems -MinQty 100) | ForEach-Object Name) -join ',' | Should -Be 'bolt,nut'
    }
    It 'MinQty 0 returns everything' { @(Get-InventoryItems -MinQty 0).Count | Should -Be 3 }
}

Describe 'Format parameter' {
    It 'Csv has a header and one row per item, invariant numbers, no total line' {
        $out = @(Format-Report -Items (Get-InventoryItems) -Format Csv)
        $out[0] | Should -Be 'Name,Qty,Price'
        $out[1] | Should -Be 'bolt,100,0.25'
        $out.Count | Should -Be 4
    }
    It 'Json is one string holding an array with a computed Value' {
        $out = Format-Report -Items (Get-InventoryItems) -Format Json
        $parsed = @($out | ConvertFrom-Json)
        $parsed.Count | Should -Be 3
        $parsed[2].Name | Should -Be 'gear'
        $parsed[2].Value | Should -Be 54
    }
    It 'rejects an unknown format' {
        { Format-Report -Items (Get-InventoryItems) -Format Xml } | Should -Throw
    }
}
EOF
echo "Inventory.ps1 Report.ps1 Inventory.Tests.ps1" > $C/t13/edit.txt
echo "Extend the inventory scripts so every test in Inventory.Tests.ps1 passes. In Inventory.ps1 give Get-InventoryItems an optional [int]\$MinQty parameter (default 0) that returns only items whose Qty is at least MinQty. In Report.ps1 give Format-Report an optional -Format parameter validated to Text, Csv or Json (default Text, which must behave exactly as today). Csv outputs a 'Name,Qty,Price' header then one 'name,qty,price' line per item using invariant-culture numbers and no total line. Json outputs a single JSON string holding an array of objects with Name, Qty, Price and Value (Qty times Price). Do not modify the test file." | sed 's/\\\$/$/g' > $C/t13/task.txt
printf '%s\n%s\n' "$(PESTER Inventory.Tests.ps1)" "$UNT Inventory.Tests.ps1" > $C/t13/check.txt
cat > $C/t13/ref/Inventory.ps1 <<'EOF'
function Get-InventoryItems {
    param([int]$MinQty = 0)
    $all = @(
        [pscustomobject]@{ Name = 'bolt'; Qty = 100; Price = 0.25 },
        [pscustomobject]@{ Name = 'nut'; Qty = 250; Price = 0.1 },
        [pscustomobject]@{ Name = 'gear'; Qty = 12; Price = 4.5 }
    )
    $all | Where-Object { $_.Qty -ge $MinQty }
}
EOF
cat > $C/t13/ref/Report.ps1 <<'EOF'
function Format-Report {
    param(
        [Parameter(Mandatory)][object[]]$Items,
        [ValidateSet('Text', 'Csv', 'Json')][string]$Format = 'Text'
    )
    $inv = [cultureinfo]::InvariantCulture
    switch ($Format) {
        'Text' {
            foreach ($i in $Items) { '{0}: {1} @ {2:N2}' -f $i.Name, $i.Qty, $i.Price }
            '{0} items, total value {1:N2}' -f $Items.Count, (($Items | ForEach-Object { $_.Qty * $_.Price } | Measure-Object -Sum).Sum)
        }
        'Csv' {
            'Name,Qty,Price'
            foreach ($i in $Items) { '{0},{1},{2}' -f $i.Name, $i.Qty, ([double]$i.Price).ToString($inv) }
        }
        'Json' {
            $rows = @($Items | ForEach-Object { [pscustomobject]@{ Name = $_.Name; Qty = $_.Qty; Price = $_.Price; Value = $_.Qty * $_.Price } })
            ConvertTo-Json -InputObject $rows -Compress
        }
    }
}
EOF
cat > $C/t13/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll {
    . $PSScriptRoot/Inventory.ps1
    . $PSScriptRoot/Report.ps1
}
Describe 'inventory hidden' {
    It 'MinQty above all items gives none' { @(Get-InventoryItems -MinQty 1000).Count | Should -Be 0 }
    It 'MinQty is inclusive' { @(Get-InventoryItems -MinQty 12).Count | Should -Be 3 }
    It 'Csv of a filtered list' {
        $out = @(Format-Report -Items (Get-InventoryItems -MinQty 250) -Format Csv)
        $out.Count | Should -Be 2
        $out[1] | Should -Be 'nut,250,0.1'
    }
    It 'Json single item is still an array' {
        $out = Format-Report -Items (Get-InventoryItems -MinQty 250) -Format Json
        $out.TrimStart()[0] | Should -Be '['
        @($out | ConvertFrom-Json).Count | Should -Be 1
    }
    It 'Json values are correct' {
        $p = @(Format-Report -Items (Get-InventoryItems) -Format Json | ConvertFrom-Json)
        $p[0].Value | Should -Be 25
        $p[1].Value | Should -Be 25
    }
    It 'Text still shows the total line' {
        @(Format-Report -Items (Get-InventoryItems) -Format Text)[-1] | Should -Be '3 items, total value 104.00'
    }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t13/hidden.txt

for t in "$C"/t*; do touch "$t/edit.txt"; done
echo "corpus built: $(ls $C | tr '\n' ' ')"
