#!/bin/bash
# Adds holdout tasks t14..t21 to ~/orch-bench/corpus WITHOUT touching t1..t13.
set -e
C=${CORPUS:-$HOME/orch-bench/corpus}
UNT='git diff --quiet $(git rev-list --max-parents=0 HEAD) --'
PESTER() { echo "pwsh -NoProfile -Command \"Invoke-Pester -Path ./$1 -CI -Output Minimal\""; }
mk() { rm -rf "$C/$1"; mkdir -p "$C/$1/base" "$C/$1/ref" "$C/$1/hidden"; echo "$2 $3" > "$C/$1/meta.txt"; }

# ============ t14  ps T2: ConvertTo-SnakeCase ============
mk t14 ps T2
echo "# case helpers" > $C/t14/base/Case.ps1
echo "Case.ps1" > $C/t14/edit.txt
cat > $C/t14/task.txt <<'EOF'
Add a function ConvertTo-SnakeCase to Case.ps1. It takes a mandatory string parameter -Text (an empty string is allowed) and returns it in snake_case. Rules: split camelCase and PascalCase words (helloWorld becomes hello_world); keep an acronym together unless it is followed by a capitalised word, in which case the acronym ends before that word's capital (XMLHttpRequest becomes xml_http_request, userID becomes user_id); an uppercase letter that follows a digit starts a new word (HTML5Parser becomes html5_parser); replace each run of spaces and hyphens with one underscore; collapse repeated underscores into one; trim leading and trailing underscores; lowercase everything.
EOF
cat > $C/t14/check.txt <<'EOF'
pwsh -NoProfile -Command '. ./Case.ps1; $cases = @(@("HelloWorld","hello_world"),@("helloWorld","hello_world"),@("XMLHttpRequest","xml_http_request"),@("already_snake","already_snake"),@("Hello World-Foo","hello_world_foo"),@("userID","user_id"),@("HTML5Parser","html5_parser")); $bad = 0; foreach ($c in $cases) { $r = ConvertTo-SnakeCase -Text $c[0]; if ($r -cne $c[1]) { "FAIL [$($c[0])] -> [$r] expected [$($c[1])]"; $bad++ } }; exit $bad'
EOF
cat > $C/t14/ref/Case.ps1 <<'EOF'
function ConvertTo-SnakeCase {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Text)
    $s = $Text -creplace '([A-Z]+)([A-Z][a-z])', '$1_$2'
    $s = $s -creplace '([a-z0-9])([A-Z])', '$1_$2'
    $s = $s -replace '[\s\-]+', '_'
    $s = $s -replace '_+', '_'
    $s.Trim('_').ToLowerInvariant()
}
EOF
cat > $C/t14/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll { . $PSScriptRoot/Case.ps1 }
Describe 'ConvertTo-SnakeCase hidden' {
    It 'handles more shapes' {
        $cases = @(@('', ''), @('ABC', 'abc'), @('getHTTPResponseCode', 'get_http_response_code'), @('a1B2', 'a1_b2'),
                   @('__Leading__', 'leading'), @('snake_Case_Mixed', 'snake_case_mixed'), @('Already  Spaced', 'already_spaced'),
                   @('simple', 'simple'), @('ID', 'id'), @('parseHTTPServer', 'parse_http_server'))
        foreach ($c in $cases) { ConvertTo-SnakeCase -Text $c[0] | Should -BeExactly $c[1] }
    }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t14/hidden.txt

# ============ t15  ps T3: Test-IPv4InSubnet ============
mk t15 ps T3
echo "# network helpers" > $C/t15/base/Net.ps1
echo "Net.ps1" > $C/t15/edit.txt
cat > $C/t15/task.txt <<'EOF'
Add a function Test-IPv4InSubnet to Net.ps1 with mandatory string parameters -Address (dotted IPv4) and -Cidr (for example 192.168.1.0/24). It returns $true when the address lies inside the subnet and $false otherwise; the base address in -Cidr may have host bits set (192.168.1.77/24 is the same subnet as 192.168.1.0/24), and prefix lengths from 0 to 32 are valid. Throw an error for an address that is not four numbers each from 0 to 255, for a -Cidr without exactly one slash, and for a prefix length outside 0 to 32.
EOF
cat > $C/t15/check.txt <<'EOF'
pwsh -NoProfile -Command '. ./Net.ps1; $cases = @(@("192.168.1.10","192.168.1.0/24",$true),@("192.168.2.10","192.168.1.0/24",$false),@("10.0.0.1","10.0.0.0/8",$true),@("11.0.0.1","10.0.0.0/8",$false),@("1.2.3.4","0.0.0.0/0",$true),@("192.168.1.5","192.168.1.5/32",$true),@("192.168.1.6","192.168.1.5/32",$false)); $bad = 0; foreach ($c in $cases) { $r = Test-IPv4InSubnet -Address $c[0] -Cidr $c[1]; if ($r -ne $c[2]) { "FAIL $($c[0]) in $($c[1]) -> $r"; $bad++ } }; exit $bad'
EOF
cat > $C/t15/ref/Net.ps1 <<'EOF'
function Test-IPv4InSubnet {
    param([Parameter(Mandatory)][string]$Address, [Parameter(Mandatory)][string]$Cidr)
    $toNum = {
        param([string]$ip)
        $parts = $ip.Split('.')
        if ($parts.Count -ne 4) { throw "Invalid IPv4 address: $ip" }
        [long]$n = 0
        foreach ($p in $parts) {
            $o = 0
            if (-not [int]::TryParse($p, [ref]$o) -or $o -lt 0 -or $o -gt 255) { throw "Invalid IPv4 address: $ip" }
            $n = $n * 256 + $o
        }
        $n
    }
    $bits = $Cidr.Split('/')
    if ($bits.Count -ne 2) { throw "Invalid CIDR: $Cidr" }
    $len = 0
    if (-not [int]::TryParse($bits[1], [ref]$len) -or $len -lt 0 -or $len -gt 32) { throw "Invalid prefix length: $Cidr" }
    $net = & $toNum $bits[0]
    $addr = & $toNum $Address
    $mask = if ($len -eq 0) { [long]0 } else { ([long]4294967295 -shl (32 - $len)) -band [long]4294967295 }
    return (($addr -band $mask) -eq ($net -band $mask))
}
EOF
cat > $C/t15/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll { . $PSScriptRoot/Net.ps1 }
Describe 'Test-IPv4InSubnet hidden' {
    It 'answers membership correctly' {
        $cases = @(@('192.168.1.255','192.168.1.0/24',$true), @('192.168.0.255','192.168.1.0/24',$false), @('172.16.5.4','172.16.0.0/12',$true),
                   @('172.32.0.1','172.16.0.0/12',$false), @('255.255.255.255','255.255.255.254/31',$true), @('255.255.255.253','255.255.255.254/31',$false),
                   @('192.168.1.5','192.168.1.77/24',$true), @('8.8.8.8','0.0.0.0/0',$true))
        foreach ($c in $cases) { (Test-IPv4InSubnet -Address $c[0] -Cidr $c[1]) | Should -Be $c[2] }
    }
    It 'returns a real boolean' { (Test-IPv4InSubnet -Address '10.0.0.1' -Cidr '10.0.0.0/8') | Should -BeOfType ([bool]) }
    It 'rejects bad input' {
        { Test-IPv4InSubnet -Address '300.1.1.1' -Cidr '10.0.0.0/8' } | Should -Throw
        { Test-IPv4InSubnet -Address '1.2.3' -Cidr '10.0.0.0/8' } | Should -Throw
        { Test-IPv4InSubnet -Address '10.0.0.1' -Cidr '10.0.0.0/33' } | Should -Throw
        { Test-IPv4InSubnet -Address '10.0.0.1' -Cidr '10.0.0.0' } | Should -Throw
        { Test-IPv4InSubnet -Address '10.0.0.1' -Cidr '10.0.0.0/8/8' } | Should -Throw
    }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t15/hidden.txt

# ============ t16  ps T1: Get-BusinessDays ============
mk t16 ps T1
echo "# date helpers" > $C/t16/base/Dates.ps1
echo "Dates.ps1" > $C/t16/edit.txt
cat > $C/t16/task.txt <<'EOF'
Add a function Get-BusinessDays to Dates.ps1 taking mandatory [datetime] parameters -Start and -End and returning the number of weekdays (Monday to Friday) from Start to End, counting both end dates and ignoring the time of day. Throw an error when End is on an earlier calendar date than Start.
EOF
cat > $C/t16/check.txt <<'EOF'
pwsh -NoProfile -Command '. ./Dates.ps1; $cases = @(@("2026-10-26","2026-10-30",5),@("2026-10-24","2026-10-25",0),@("2026-10-23","2026-10-26",2),@("2026-10-28","2026-10-28",1),@("2026-10-26","2026-11-02",6)); $bad = 0; foreach ($c in $cases) { $r = Get-BusinessDays -Start ([datetime]$c[0]) -End ([datetime]$c[1]); if ($r -ne $c[2]) { "FAIL $($c[0])..$($c[1]) -> $r expected $($c[2])"; $bad++ } }; exit $bad'
EOF
cat > $C/t16/ref/Dates.ps1 <<'EOF'
function Get-BusinessDays {
    param([Parameter(Mandatory)][datetime]$Start, [Parameter(Mandatory)][datetime]$End)
    if ($End.Date -lt $Start.Date) { throw 'End must not be before Start' }
    $count = 0
    for ($d = $Start.Date; $d -le $End.Date; $d = $d.AddDays(1)) {
        if ($d.DayOfWeek -ne 'Saturday' -and $d.DayOfWeek -ne 'Sunday') { $count++ }
    }
    $count
}
EOF
cat > $C/t16/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll { . $PSScriptRoot/Dates.ps1 }
Describe 'Get-BusinessDays hidden' {
    It 'counts whole years and months' {
        Get-BusinessDays -Start ([datetime]'2026-01-01') -End ([datetime]'2026-12-31') | Should -Be 261
        Get-BusinessDays -Start ([datetime]'2026-02-01') -End ([datetime]'2026-02-28') | Should -Be 20
        Get-BusinessDays -Start ([datetime]'2028-02-28') -End ([datetime]'2028-03-01') | Should -Be 3
    }
    It 'ignores the time of day' {
        Get-BusinessDays -Start ([datetime]'2026-10-26 23:00') -End ([datetime]'2026-10-27 01:00') | Should -Be 2
        Get-BusinessDays -Start ([datetime]'2026-10-26 18:00') -End ([datetime]'2026-10-26 08:00') | Should -Be 1
    }
    It 'handles weekend endpoints' {
        Get-BusinessDays -Start ([datetime]'2026-10-24') -End ([datetime]'2026-10-26') | Should -Be 1
        Get-BusinessDays -Start ([datetime]'2026-10-30') -End ([datetime]'2026-11-01') | Should -Be 1
    }
    It 'rejects a reversed range' { { Get-BusinessDays -Start ([datetime]'2026-10-27') -End ([datetime]'2026-10-26') } | Should -Throw }
    It 'returns an integer' { (Get-BusinessDays -Start ([datetime]'2026-10-26') -End ([datetime]'2026-10-26')) | Should -BeOfType ([int]) }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t16/hidden.txt

# ============ t17  ps T2: Expand-Template ============
mk t17 ps T2
echo "# template helpers" > $C/t17/base/Template.ps1
echo "Template.ps1" > $C/t17/edit.txt
cat > $C/t17/task.txt <<'EOF'
Add a function Expand-Template to Template.ps1 taking a mandatory [string] -Template and a mandatory [hashtable] -Values. It replaces every placeholder of the form {{key}} (optional spaces just inside the braces, so {{ key }} also works; keys are letters, digits and underscores) with the value for that key converted to a string. A placeholder whose key is not in the hashtable is left exactly as written. A $null value becomes an empty string. It is a single pass: text inserted for one placeholder is never scanned for further placeholders, and a value such as '$1' must appear literally in the output.
EOF
cat > $C/t17/check.txt <<'EOF'
pwsh -NoProfile -Command '. ./Template.ps1; $bad = 0; $t = @( @("Hello {{name}}!", @{name="World"}, "Hello World!"), @("{{ a }}-{{b}}", @{a=1;b=2}, "1-2"), @("keep {{missing}} here", @{x=1}, "keep {{missing}} here"), @("{{n}} and {{n}}", @{n="x"}, "x and x"), @("count: {{c}}", @{c=5}, "count: 5") ); foreach ($c in $t) { $r = Expand-Template -Template $c[0] -Values $c[1]; if ($r -cne $c[2]) { "FAIL [$($c[0])] -> [$r] expected [$($c[2])]"; $bad++ } }; exit $bad'
EOF
cat > $C/t17/ref/Template.ps1 <<'EOF'
function Expand-Template {
    param([Parameter(Mandatory)][string]$Template, [Parameter(Mandatory)][hashtable]$Values)
    [regex]::Replace($Template, '\{\{\s*([A-Za-z0-9_]+)\s*\}\}', {
        param($m)
        $k = $m.Groups[1].Value
        if ($Values.ContainsKey($k)) { [string]$Values[$k] } else { $m.Value }
    })
}
EOF
cat > $C/t17/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll { . $PSScriptRoot/Template.ps1 }
Describe 'Expand-Template hidden' {
    It 'keeps dollar signs literal' { Expand-Template -Template 'cost: {{p}}' -Values @{ p = '$1 and $&' } | Should -BeExactly 'cost: $1 and $&' }
    It 'is single pass' { Expand-Template -Template '{{a}}' -Values @{ a = '{{b}}'; b = 'x' } | Should -BeExactly '{{b}}' }
    It 'handles null as empty' { Expand-Template -Template '[{{a}}]' -Values @{ a = $null } | Should -BeExactly '[]' }
    It 'handles underscores digits and multiple lines' {
        Expand-Template -Template "{{a_1}}`n{{ b2 }}" -Values @{ a_1 = 'one'; b2 = 'two' } | Should -BeExactly "one`ntwo"
    }
    It 'leaves malformed placeholders alone' {
        Expand-Template -Template '{{ }} {a} {{b' -Values @{ b = 'x' } | Should -BeExactly '{{ }} {a} {{b'
    }
    It 'returns the template when there are no placeholders' { Expand-Template -Template 'plain' -Values @{} | Should -BeExactly 'plain' }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t17/hidden.txt

# ============ t18  ps T4: log parsing across two files ============
mk t18 ps T4
echo "# log parsing" > $C/t18/base/Log.ps1
echo "# log summaries" > $C/t18/base/Summary.ps1
cat > $C/t18/base/Log.Tests.ps1 <<'EOF'
BeforeAll {
    . $PSScriptRoot/Log.ps1
    . $PSScriptRoot/Summary.ps1
}

Describe 'ConvertFrom-LogLine' {
    It 'parses the four fields' {
        $r = ConvertFrom-LogLine -Line '2026-01-02T10:00:00Z ERROR payments Card declined: code 51'
        $r.Level | Should -Be 'ERROR'
        $r.Service | Should -Be 'payments'
        $r.Message | Should -Be 'Card declined: code 51'
        $r.Time.ToString('s') | Should -Be '2026-01-02T10:00:00'
    }
    It 'returns null for blank or malformed lines' {
        ConvertFrom-LogLine -Line '' | Should -BeNullOrEmpty
        ConvertFrom-LogLine -Line 'not a log line' | Should -BeNullOrEmpty
        ConvertFrom-LogLine -Line '2026-01-02T10:00:00Z LOUD svc hi' | Should -BeNullOrEmpty
    }
}

Describe 'Get-LogSummary' {
    BeforeAll {
        $script:lines = @(
            '2026-01-02T10:05:00Z ERROR payments Card declined',
            '2026-01-02T10:00:00Z INFO  web Started',
            'garbage line',
            '2026-01-02T10:01:00Z ERROR auth Token expired',
            '2026-01-02T10:02:00Z ERROR auth Token expired again',
            '2026-01-02T10:03:00Z WARN  web Slow response'
        )
    }
    It 'counts parsed lines and levels, ignoring malformed ones' {
        $s = Get-LogSummary -Lines $script:lines
        $s.Total | Should -Be 5
        $s.ByLevel['ERROR'] | Should -Be 3
        $s.ByLevel['WARN'] | Should -Be 1
        $s.ByLevel['INFO'] | Should -Be 1
    }
    It 'names the service with the most errors, ties broken alphabetically' {
        (Get-LogSummary -Lines $script:lines).TopService | Should -Be 'auth'
        (Get-LogSummary -Lines @('2026-01-02T10:00:00Z ERROR b x', '2026-01-02T10:00:01Z ERROR a y')).TopService | Should -Be 'a'
    }
    It 'reports the chronologically first error, or null when there are none' {
        (Get-LogSummary -Lines $script:lines).FirstError.ToString('s') | Should -Be '2026-01-02T10:01:00'
        (Get-LogSummary -Lines @('2026-01-02T10:00:00Z INFO web ok')).FirstError | Should -BeNullOrEmpty
        (Get-LogSummary -Lines @('2026-01-02T10:00:00Z INFO web ok')).TopService | Should -BeNullOrEmpty
    }
}
EOF
echo "Log.ps1 Summary.ps1 Log.Tests.ps1" > $C/t18/edit.txt
cat > $C/t18/task.txt <<'EOF'
Implement log parsing across two files so that every test in Log.Tests.ps1 passes; do not modify the test file. In Log.ps1 add ConvertFrom-LogLine -Line: a log line looks like '2026-01-02T10:00:00Z ERROR payments Card declined: code 51', that is a UTC timestamp, a level (DEBUG, INFO, WARN or ERROR, upper case), a service name without spaces, then the rest of the line as the message (one or more spaces separate the fields). It returns an object with Time (a UTC datetime), Level, Service and Message, or $null for blank or malformed lines. In Summary.ps1 add Get-LogSummary -Lines (an array of strings): it parses every line with ConvertFrom-LogLine, ignores the ones that return $null, and returns an object with Total (number of parsed lines), ByLevel (a hashtable of level to count, only levels that occur), TopService (the service with the most ERROR lines, ties broken alphabetically, $null if there are no errors) and FirstError (the Time of the chronologically earliest ERROR line, or $null if none).
EOF
printf '%s\n%s\n' "$(PESTER Log.Tests.ps1)" "$UNT Log.Tests.ps1" > $C/t18/check.txt
cat > $C/t18/ref/Log.ps1 <<'EOF'
function ConvertFrom-LogLine {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Line)
    $m = [regex]::Match($Line, '^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+(DEBUG|INFO|WARN|ERROR)\s+(\S+)\s+(.*?)\s*$')
    if (-not $m.Success) { return $null }
    $styles = [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal
    [pscustomobject]@{
        Time    = [datetime]::ParseExact($m.Groups[1].Value, "yyyy-MM-dd'T'HH:mm:ss'Z'", [cultureinfo]::InvariantCulture, $styles)
        Level   = $m.Groups[2].Value
        Service = $m.Groups[3].Value
        Message = $m.Groups[4].Value
    }
}
EOF
cat > $C/t18/ref/Summary.ps1 <<'EOF'
function Get-LogSummary {
    param([Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Lines)
    $parsed = @($Lines | ForEach-Object { ConvertFrom-LogLine -Line $_ } | Where-Object { $null -ne $_ })
    $byLevel = @{}
    foreach ($e in $parsed) { $byLevel[$e.Level] = 1 + [int]$byLevel[$e.Level] }
    $errors = @($parsed | Where-Object { $_.Level -eq 'ERROR' })
    $top = $null; $first = $null
    if ($errors.Count -gt 0) {
        $top = ($errors | Group-Object Service | Sort-Object @{ Expression = 'Count'; Descending = $true }, Name | Select-Object -First 1).Name
        $first = ($errors | Sort-Object Time | Select-Object -First 1).Time
    }
    [pscustomobject]@{ Total = $parsed.Count; ByLevel = $byLevel; TopService = $top; FirstError = $first }
}
EOF
cat > $C/t18/hidden/Hidden.Tests.ps1 <<'EOF'
BeforeAll {
    . $PSScriptRoot/Log.ps1
    . $PSScriptRoot/Summary.ps1
}
Describe 'log parsing hidden' {
    It 'accepts several spaces between fields and all four levels' {
        foreach ($lvl in 'DEBUG', 'INFO', 'WARN', 'ERROR') {
            $r = ConvertFrom-LogLine -Line "2026-03-04T05:06:07Z $lvl   svc-1    some   message  "
            $r.Level | Should -Be $lvl
            $r.Service | Should -Be 'svc-1'
            $r.Message | Should -Be 'some   message'
        }
    }
    It 'rejects lower-case levels and bad timestamps' {
        ConvertFrom-LogLine -Line '2026-03-04T05:06:07Z error svc msg' | Should -BeNullOrEmpty
        ConvertFrom-LogLine -Line '2026-03-04 05:06:07 ERROR svc msg' | Should -BeNullOrEmpty
    }
    It 'summarises an empty list' {
        $s = Get-LogSummary -Lines @()
        $s.Total | Should -Be 0
        $s.TopService | Should -BeNullOrEmpty
        $s.FirstError | Should -BeNullOrEmpty
        $s.ByLevel.Count | Should -Be 0
    }
    It 'breaks error-count ties alphabetically and finds the earliest error out of order' {
        $s = Get-LogSummary -Lines @('2026-01-01T00:00:09Z ERROR zeta a', '2026-01-01T00:00:03Z ERROR mid b', '2026-01-01T00:00:05Z ERROR zeta c', '2026-01-01T00:00:06Z ERROR mid d')
        $s.TopService | Should -Be 'mid'
        $s.FirstError.ToString('s') | Should -Be '2026-01-01T00:00:03'
        $s.ByLevel['ERROR'] | Should -Be 4
        $s.ByLevel.ContainsKey('INFO') | Should -BeFalse
    }
    It 'counts warnings and debug lines in ByLevel' {
        $s = Get-LogSummary -Lines @('2026-01-01T00:00:01Z DEBUG x a', '2026-01-01T00:00:02Z DEBUG x b', '2026-01-01T00:00:03Z WARN y c')
        $s.ByLevel['DEBUG'] | Should -Be 2
        $s.Total | Should -Be 3
    }
}
EOF
echo "$(PESTER Hidden.Tests.ps1)" > $C/t18/hidden.txt

# ============ t19  py T2: parse_duration bugfix ============
mk t19 py T2
mkdir -p $C/t19/base/tests; : > $C/t19/base/conftest.py
cat > $C/t19/base/durations.py <<'EOF'
import re


def parse_duration(text):
    """Convert strings like '1h30m' or '2d 4h' into a number of seconds."""
    units = {"h": 3600, "m": 60, "s": 1}
    total = 0
    for number, unit in re.findall(r"(\d+)([hms])", text):
        total += int(number) * units[unit]
    return total
EOF
cat > $C/t19/base/tests/test_durations.py <<'EOF'
import pytest
from durations import parse_duration


def test_basic_units():
    assert parse_duration("45s") == 45
    assert parse_duration("2m") == 120
    assert parse_duration("3h") == 10800
    assert parse_duration("2d") == 172800


def test_combinations_and_whitespace():
    assert parse_duration("1h30m") == 5400
    assert parse_duration(" 1h 30m ") == 5400
    assert parse_duration("1d2h3m4s") == 93784


@pytest.mark.parametrize("bad", ["", "abc", "10", "1x", "1h30", "h", "1h junk"])
def test_invalid_input_raises(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)
EOF
echo "durations.py tests/test_durations.py" > $C/t19/edit.txt
echo "parse_duration in durations.py has bugs. Fix them so every test in tests/test_durations.py passes. Do not modify the tests." > $C/t19/task.txt
printf '%s\n%s\n' "python -m pytest -q -p no:cacheprovider" "$UNT tests" > $C/t19/check.txt
cat > $C/t19/ref/durations.py <<'EOF'
import re

_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_duration(text):
    """Convert strings like '1h30m' or '2d 4h' into a number of seconds."""
    if not re.fullmatch(r"\s*(?:\d+\s*[dhms]\s*)+", text):
        raise ValueError(f"invalid duration: {text!r}")
    return sum(int(n) * _UNITS[u] for n, u in re.findall(r"(\d+)\s*([dhms])", text))
EOF
mkdir -p $C/t19/hidden/tests
cat > $C/t19/hidden/tests/test_hidden.py <<'EOF'
import pytest
from durations import parse_duration


def test_more_valid():
    assert parse_duration("0s") == 0
    assert parse_duration("100m") == 6000
    assert parse_duration("1h1h") == 7200
    assert parse_duration("1d 1d") == 172800
    assert parse_duration("\t5s\n") == 5


# Only cases that follow from the visible tests (a unit is required after every number, nothing else may appear).
# Removed after the overnight run: "3 4h" (whether a space may sit inside a number is never specified) and None
# (the error type for a non-string was never specified).
@pytest.mark.parametrize("bad", ["1.5h", "-5s", "1h-5m", "five minutes", "1 h 2"])
def test_more_invalid(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)
EOF
echo "python -m pytest -q -p no:cacheprovider tests/test_hidden.py" > $C/t19/hidden.txt

# ============ t20  py T3: sliding-window RateLimiter ============
mk t20 py T3
mkdir -p $C/t20/base/tests; : > $C/t20/base/conftest.py
cat > $C/t20/base/ratelimit.py <<'EOF'
import time


class RateLimiter:
    """Sliding-window rate limiter.

    RateLimiter(limit, window, clock=time.monotonic)
      - limit: maximum allowed calls per key inside any window (>= 1, else ValueError)
      - window: window length in seconds (> 0, else ValueError)
      - clock: zero-argument callable returning the current time

    allow(key) -> bool: True and the call is recorded when fewer than `limit` allowed calls for this key happened in the
        last `window` seconds. A call made at time t stops counting once clock() >= t + window. A refused call is not recorded.
    remaining(key) -> int: how many more calls would be allowed right now for this key.
    Keys are independent of each other.
    """

    def __init__(self, limit, window, clock=time.monotonic):
        raise NotImplementedError

    def allow(self, key):
        raise NotImplementedError

    def remaining(self, key):
        raise NotImplementedError
EOF
cat > $C/t20/base/tests/test_ratelimit.py <<'EOF'
import pytest
from ratelimit import RateLimiter


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(limit=2, window=10):
    c = Clock()
    return RateLimiter(limit, window, clock=c), c


def test_allows_up_to_limit_then_refuses():
    r, _ = make()
    assert r.allow("a") and r.allow("a")
    assert not r.allow("a")


def test_window_expiry_boundary():
    r, clk = make(limit=1, window=10)
    assert r.allow("a")
    clk.t = 9.99
    assert not r.allow("a")
    clk.t = 10
    assert r.allow("a")


def test_keys_are_independent():
    r, _ = make(limit=1)
    assert r.allow("a")
    assert r.allow("b")
    assert not r.allow("a")


def test_refused_calls_are_not_recorded():
    r, clk = make(limit=1, window=10)
    assert r.allow("a")
    clk.t = 5
    assert not r.allow("a")
    clk.t = 10          # only the call at t=0 counts, and it has expired
    assert r.allow("a")


def test_sliding_not_fixed_window():
    r, clk = make(limit=2, window=10)
    assert r.allow("a")          # t=0
    clk.t = 6
    assert r.allow("a")          # t=6
    clk.t = 10
    assert r.allow("a")          # t=0 expired, t=6 still counts -> one slot free
    assert not r.allow("a")


def test_remaining():
    r, clk = make(limit=3, window=10)
    assert r.remaining("a") == 3
    r.allow("a")
    assert r.remaining("a") == 2
    clk.t = 10
    assert r.remaining("a") == 3


def test_invalid_arguments():
    with pytest.raises(ValueError):
        RateLimiter(0, 5)
    with pytest.raises(ValueError):
        RateLimiter(1, 0)
EOF
echo "ratelimit.py tests/test_ratelimit.py" > $C/t20/edit.txt
echo "Implement the RateLimiter class in ratelimit.py exactly as its docstring describes so that every test in tests/test_ratelimit.py passes. Do not modify the tests." > $C/t20/task.txt
printf '%s\n%s\n' "python -m pytest -q -p no:cacheprovider" "$UNT tests" > $C/t20/check.txt
cat > $C/t20/ref/ratelimit.py <<'EOF'
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit, window, clock=time.monotonic):
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if window <= 0:
            raise ValueError("window must be > 0")
        self.limit, self.window, self.clock = limit, window, clock
        self._calls = defaultdict(deque)

    def _prune(self, key):
        q, now = self._calls[key], self.clock()
        while q and now >= q[0] + self.window:
            q.popleft()
        return q

    def allow(self, key):
        q = self._prune(key)
        if len(q) < self.limit:
            q.append(self.clock())
            return True
        return False

    def remaining(self, key):
        return self.limit - len(self._prune(key))
EOF
mkdir -p $C/t20/hidden/tests
cat > $C/t20/hidden/tests/test_hidden.py <<'EOF'
import pytest
from ratelimit import RateLimiter


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(limit=2, window=10):
    c = Clock()
    return RateLimiter(limit, window, clock=c), c


def test_remaining_never_negative_and_tracks_refusals():
    r, _ = make(limit=2)
    r.allow("a"); r.allow("a"); r.allow("a"); r.allow("a")
    assert r.remaining("a") == 0


def test_limit_one_precise_edges():
    r, clk = make(limit=1, window=1)
    assert r.allow("k")
    clk.t = 0.999
    assert not r.allow("k")
    clk.t = 1.0
    assert r.allow("k")
    clk.t = 1.5
    assert not r.allow("k")


def test_many_keys_do_not_interfere():
    r, _ = make(limit=1)
    assert all(r.allow(f"k{i}") for i in range(50))
    assert not any(r.allow(f"k{i}") for i in range(50))


def test_staggered_expiry_frees_one_slot_at_a_time():
    r, clk = make(limit=3, window=10)
    for t in (0, 2, 4):
        clk.t = t
        assert r.allow("a")
    clk.t = 9
    assert not r.allow("a")
    clk.t = 10
    assert r.allow("a") and not r.allow("a")
    clk.t = 12
    assert r.allow("a")


def test_non_integer_window_and_negative_limit():
    r, clk = make(limit=1, window=0.5)
    assert r.allow("a")
    clk.t = 0.5
    assert r.allow("a")
    with pytest.raises(ValueError):
        RateLimiter(-1, 5)
    with pytest.raises(ValueError):
        RateLimiter(1, -2)
EOF
echo "python -m pytest -q -p no:cacheprovider tests/test_hidden.py" > $C/t20/hidden.txt

# ============ t21  py T3: topological_sort ============
mk t21 py T3
mkdir -p $C/t21/base/tests; : > $C/t21/base/conftest.py
cat > $C/t21/base/toposort.py <<'EOF'
def topological_sort(deps):
    """Order the nodes of a dependency graph so every node comes after the nodes it depends on.

    deps maps a node to the list of nodes it depends on (its prerequisites). Nodes that only appear as
    prerequisites are part of the graph too. When several nodes are ready at once, take them in alphabetical
    order. Raise ValueError('cycle detected') if the graph contains a cycle. Return a list of all nodes.
    """
    raise NotImplementedError
EOF
cat > $C/t21/base/tests/test_toposort.py <<'EOF'
import pytest
from toposort import topological_sort


def test_simple_chain():
    assert topological_sort({"c": ["b"], "b": ["a"], "a": []}) == ["a", "b", "c"]


def test_alphabetical_among_ready_nodes():
    assert topological_sort({"d": ["a"], "c": ["a"], "b": [], "a": []}) == ["a", "b", "c", "d"]


def test_nodes_only_seen_as_prerequisites_are_included():
    assert topological_sort({"app": ["lib", "log"]}) == ["lib", "log", "app"]


def test_empty_graph():
    assert topological_sort({}) == []


def test_cycle_raises():
    with pytest.raises(ValueError, match="cycle"):
        topological_sort({"a": ["b"], "b": ["a"]})


def test_self_dependency_is_a_cycle():
    with pytest.raises(ValueError):
        topological_sort({"a": ["a"]})


def test_does_not_modify_input():
    g = {"b": ["a"], "a": []}
    topological_sort(g)
    assert g == {"b": ["a"], "a": []}
EOF
echo "toposort.py tests/test_toposort.py" > $C/t21/edit.txt
echo "Implement topological_sort in toposort.py exactly as its docstring describes so that every test in tests/test_toposort.py passes. Do not modify the tests." > $C/t21/task.txt
printf '%s\n%s\n' "python -m pytest -q -p no:cacheprovider" "$UNT tests" > $C/t21/check.txt
cat > $C/t21/ref/toposort.py <<'EOF'
import heapq


def topological_sort(deps):
    nodes = set(deps)
    for reqs in deps.values():
        nodes.update(reqs)
    indegree = {n: 0 for n in nodes}
    dependents = {n: [] for n in nodes}
    for node, reqs in deps.items():
        for r in set(reqs):
            indegree[node] += 1
            dependents[r].append(node)
    ready = [n for n, d in indegree.items() if d == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        n = heapq.heappop(ready)
        order.append(n)
        for m in dependents[n]:
            indegree[m] -= 1
            if indegree[m] == 0:
                heapq.heappush(ready, m)
    if len(order) != len(nodes):
        raise ValueError("cycle detected")
    return order
EOF
mkdir -p $C/t21/hidden/tests
cat > $C/t21/hidden/tests/test_hidden.py <<'EOF'
import pytest
from toposort import topological_sort


def test_diamond():
    g = {"d": ["b", "c"], "b": ["a"], "c": ["a"]}
    assert topological_sort(g) == ["a", "b", "c", "d"]


def test_ready_set_order_is_alphabetical_at_every_step():
    g = {"z": [], "y": ["z"], "a": ["z"], "m": []}
    assert topological_sort(g) == ["m", "z", "a", "y"]


def test_duplicate_prerequisites_are_harmless():
    assert topological_sort({"b": ["a", "a"], "a": []}) == ["a", "b"]


def test_longer_cycle_and_cycle_with_tail():
    with pytest.raises(ValueError, match="cycle"):
        topological_sort({"a": ["c"], "b": ["a"], "c": ["b"]})
    with pytest.raises(ValueError, match="cycle"):
        topological_sort({"x": ["a"], "a": ["b"], "b": ["a"]})


def test_integer_nodes_and_independent_roots():
    assert topological_sort({3: [1], 2: [], 1: []}) == [1, 2, 3]


def test_returns_all_nodes_exactly_once():
    g = {f"n{i}": [f"n{i-1}"] for i in range(1, 30)}
    out = topological_sort(g)
    assert out == [f"n{i}" for i in range(30)] and len(set(out)) == 30
EOF
echo "python -m pytest -q -p no:cacheprovider tests/test_hidden.py" > $C/t21/hidden.txt

for t in t14 t15 t16 t17 t18 t19 t20 t21; do touch "$C/$t/edit.txt"; done
echo "holdout corpus added: $(ls $C | sort -V | tr '\n' ' ')"
