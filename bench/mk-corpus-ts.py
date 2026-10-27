#!/usr/bin/env python3
"""TypeScript pilot tasks ts1..ts5, cut from the user's Bosun repo (github.com/reallango/Bosun @ 11353b5).
Each task is a slim slice of the real repo: the real source file(s), Bosun's tsconfig (minus the Next.js plugin),
a visible vitest test, hidden tests, and a reference solution. Writes to $CORPUS (default ~/orch-bench/corpus-ts)."""
import json, os, shutil
from pathlib import Path

SRC = Path(os.environ.get("BOSUN", Path.home() / "ts-src" / "Bosun"))
C = Path(os.environ.get("CORPUS", Path.home() / "orch-bench" / "corpus-ts"))
NM = "ln -sfn /opt/tsdeps/node_modules node_modules && "
TSC = NM + "./node_modules/.bin/tsc --noEmit -p ."

TSCONFIG = {"compilerOptions": {"lib": ["dom", "dom.iterable", "esnext"], "allowJs": True, "skipLibCheck": True,
                                "strict": True, "noEmit": True, "esModuleInterop": True, "module": "esnext",
                                "moduleResolution": "bundler", "resolveJsonModule": True, "isolatedModules": True,
                                "types": ["node"], "paths": {"@/*": ["./src/*"]}},
            "include": ["src/**/*", "tests/**/*", "*.ts"], "exclude": ["node_modules"]}
PACKAGE = {"name": "bosun-slice", "version": "0.1.0", "private": True,
           "scripts": {"test": "vitest run", "typecheck": "tsc --noEmit"},
           "devDependencies": {"typescript": "^5", "vitest": "^2", "@types/node": "^20"}}


def mk(name, lang_tier, files, task, visible, hidden, ref):
    """files: repo paths copied from Bosun into base/. visible/hidden/ref: {path: content}."""
    d = C / name
    shutil.rmtree(d, ignore_errors=True)
    for sub in ("base", "ref", "hidden"):
        (d / sub).mkdir(parents=True)
    (d / "meta.txt").write_text(lang_tier + "\n")
    base = d / "base"
    for f in files:
        (base / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SRC / f, base / f)
    (base / "tsconfig.json").write_text(json.dumps(TSCONFIG, indent=2) + "\n")
    (base / "package.json").write_text(json.dumps(PACKAGE, indent=2) + "\n")
    (base / ".gitignore").write_text("node_modules\n*.tsbuildinfo\n")
    for tree, content in ((base, visible), (d / "hidden", hidden), (d / "ref", ref)):
        for p, text in content.items():
            (tree / p).parent.mkdir(parents=True, exist_ok=True)
            (tree / p).write_text(text.lstrip("\n"))
    vis = next(iter(visible))
    (d / "task.txt").write_text(" ".join(task.split()) + "\n")
    (d / "edit.txt").write_text(" ".join(files + [vis]) + "\n")
    (d / "check.txt").write_text(f"{TSC}\n{NM}./node_modules/.bin/vitest run --reporter=dot {vis}\n")
    (d / "hidden.txt").write_text(f"{NM}./node_modules/.bin/vitest run --reporter=dot\n")


# ============ ts1  T1: parseSizeToMB understands df -h / free -h sizes ============
mk("ts1", "ts T1", ["src/lib/utils/parsers.ts"], """
In src/lib/utils/parsers.ts, extend parseSizeToMB so it also understands the size strings printed by df -h, free -h
and docker system df: single-letter suffixes K, M, G and T (for example 1.5G or 512M), the IEC suffixes KiB, MiB, GiB
and TiB, and B for plain bytes, alongside the KB/MB/GB/TB it already accepts. Suffixes are case-insensitive and may be
separated from the number by spaces; leading and trailing whitespace is ignored. All units are binary
(1K = 1KB = 1KiB = 1024 bytes, 1M = 1024K, and so on); a number with no suffix is bytes, as today. Anything that is not
a non-negative number followed by an optional known suffix returns 0. Keep the signature and the other functions
unchanged.""",
   {"tests/parsers.test.ts": """
import { describe, it, expect } from 'vitest';
import { parseSizeToMB } from '../src/lib/utils/parsers';

describe('parseSizeToMB', () => {
  it('reads df -h style sizes', () => {
    expect(parseSizeToMB('1.5G')).toBe(1536);
    expect(parseSizeToMB('512M')).toBe(512);
  });
  it('still reads the old forms', () => {
    expect(parseSizeToMB('2GB')).toBe(2048);
    expect(parseSizeToMB('abc')).toBe(0);
  });
});
"""},
   {"tests/parsers.hidden.test.ts": """
import { describe, it, expect } from 'vitest';
import { parseSizeToMB, parseKeyValue, truncate } from '../src/lib/utils/parsers';

describe('parseSizeToMB hidden', () => {
  it.each([
    ['1.5G', 1536], ['512M', 512], ['2GiB', 2048], ['1024 KiB', 1], ['1048576B', 1], ['1048576', 1],
    [' 3 GB ', 3072], ['1T', 1048576], ['2 tib', 2097152], ['1.5g', 1536], ['256mib', 256], ['0', 0], ['2048K', 2],
  ])('%s', (input, mb) => {
    expect(parseSizeToMB(input as string)).toBeCloseTo(mb as number, 9);
  });
  it('kilobytes are fractional megabytes', () => {
    expect(parseSizeToMB('100kb')).toBeCloseTo(100 / 1024, 9);
  });
  it.each(['', 'abc', '-5G', '10X', '5 GBs', 'G'])('rejects %j', (input) => {
    expect(parseSizeToMB(input)).toBe(0);
  });
  it('leaves the other helpers alone', () => {
    expect(parseKeyValue('A="x=y"\\nB=2')).toEqual({ A: 'x=y', B: '2' });
    expect(truncate('abcdefgh', 6)).toBe('abc...');
  });
});
"""},
   {"src/lib/utils/parsers.ts": """
export function parseKeyValue(text: string): Record<string, string> {
  const result: Record<string, string> = {};
  text.split('\\n').forEach(line => {
    const [key, ...rest] = line.split('=');
    if (key && rest.length) {
      result[key.trim()] = rest.join('=').replace(/"/g, '').trim();
    }
  });
  return result;
}

// Powers of 1024 relative to a byte; every unit is binary.
const UNIT_POWER: Record<string, number> = {
  B: 0,
  K: 1, KB: 1, KIB: 1,
  M: 2, MB: 2, MIB: 2,
  G: 3, GB: 3, GIB: 3,
  T: 4, TB: 4, TIB: 4,
};

export function parseSizeToMB(size: string): number {
  const match = size.trim().match(/^(\\d+(?:\\.\\d+)?)\\s*([a-z]*)$/i);
  if (!match) return 0;
  const power = UNIT_POWER[(match[2] || 'B').toUpperCase()];
  if (power === undefined) return 0;
  return parseFloat(match[1]) * Math.pow(1024, power - 2);
}

export function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.substring(0, maxLength - 3) + '...';
}
"""})

# ============ ts2  T2: formatDistanceToNow with weeks, years, future and a reference time ============
mk("ts2", "ts T2", ["src/lib/utils/date.ts"], """
Improve formatDistanceToNow in src/lib/utils/date.ts. Add an optional second parameter now: Date (default: the
current time) so callers and tests can pass the reference time; existing callers pass one argument and must keep
compiling. For a date in the past: under 60 seconds gives 'just now'; under 60 minutes '<n>m ago'; under 24 hours
'<n>h ago'; under 7 days '<n>d ago'; under 365 days '<n>w ago' (whole weeks); otherwise '<n>y ago' (whole 365-day
years). Always round down. A date in the future uses the same units with an 'in ' prefix instead of the ' ago' suffix
('in 5m', 'in 2h', 'in 3d', 'in 1w', 'in 2y'), and is also 'just now' when under 60 seconds away. An invalid Date
(its time is NaN) returns an empty string.""",
   {"tests/date.test.ts": """
import { describe, it, expect } from 'vitest';
import { formatDistanceToNow } from '../src/lib/utils/date';

const NOW = new Date('2026-03-15T12:00:00Z');
const ago = (ms: number) => new Date(NOW.getTime() - ms);

describe('formatDistanceToNow', () => {
  it('uses weeks after a week', () => {
    expect(formatDistanceToNow(ago(10 * 86400e3), NOW)).toBe('1w ago');
  });
  it('handles the future and very recent dates', () => {
    expect(formatDistanceToNow(ago(-5 * 60e3), NOW)).toBe('in 5m');
    expect(formatDistanceToNow(ago(30e3), NOW)).toBe('just now');
  });
});
"""},
   {"tests/date.hidden.test.ts": """
import { describe, it, expect, vi, afterEach } from 'vitest';
import { formatDistanceToNow } from '../src/lib/utils/date';

const NOW = new Date('2026-03-15T12:00:00Z');
const S = 1e3, M = 60e3, H = 3600e3, D = 86400e3;
const at = (offsetMs: number) => new Date(NOW.getTime() + offsetMs);

describe('formatDistanceToNow hidden', () => {
  afterEach(() => { vi.useRealTimers(); });
  it.each([
    [-59 * S, 'just now'], [-60 * S, '1m ago'], [-59 * M, '59m ago'], [-60 * M, '1h ago'], [-23 * H - 59 * M, '23h ago'],
    [-24 * H, '1d ago'], [-7 * D + 1, '6d ago'], [-7 * D, '1w ago'], [-20 * D, '2w ago'], [-364 * D, '52w ago'],
    [-365 * D, '1y ago'], [-800 * D, '2y ago'], [0, 'just now'],
  ])('past offset %d', (off, text) => {
    expect(formatDistanceToNow(at(off as number), NOW)).toBe(text);
  });
  it.each([
    [59 * S, 'just now'], [90 * S, 'in 1m'], [2 * H + 5 * M, 'in 2h'], [3 * D, 'in 3d'], [8 * D, 'in 1w'], [731 * D, 'in 2y'],
  ])('future offset %d', (off, text) => {
    expect(formatDistanceToNow(at(off as number), NOW)).toBe(text);
  });
  it('invalid dates give an empty string', () => {
    expect(formatDistanceToNow(new Date('not a date'), NOW)).toBe('');
  });
  it('defaults to the current time', () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    expect(formatDistanceToNow(at(-3 * H))).toBe('3h ago');
  });
});
"""},
   {"src/lib/utils/date.ts": """
export function formatDistanceToNow(date: Date, now: Date = new Date()): string {
  const diff = now.getTime() - date.getTime();
  if (Number.isNaN(diff)) return '';
  const seconds = Math.floor(Math.abs(diff) / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  let amount: string;
  if (days >= 365) amount = `${Math.floor(days / 365)}y`;
  else if (days >= 7) amount = `${Math.floor(days / 7)}w`;
  else if (days > 0) amount = `${days}d`;
  else if (hours > 0) amount = `${hours}h`;
  else if (minutes > 0) amount = `${minutes}m`;
  else return 'just now';
  return diff >= 0 ? `${amount} ago` : `in ${amount}`;
}
"""})

# ============ ts3  T3: login lockout is cut short; reset after a successful login ============
RL = (SRC / "src/lib/utils/rate-limiter.ts").read_text()
RL_REF = RL.replace("""    entry.attempts = entry.attempts.filter(t => now - t < windowMs);
    if (entry.attempts.length === 0) {
      map.delete(key);
    }""", """    entry.attempts = entry.attempts.filter(t => now - t < windowMs);
    const locked = entry.lockedUntil !== undefined && now < entry.lockedUntil;
    if (entry.attempts.length === 0 && !locked) {
      map.delete(key);
    }""").replace("""  if (entry.lockedUntil && Date.now() < entry.lockedUntil) {
    return { allowed: false, remainingAttempts: 0, lockedUntil: entry.lockedUntil };
  }
""", """  if (entry.lockedUntil !== undefined) {
    if (Date.now() < entry.lockedUntil) {
      return { allowed: false, remainingAttempts: 0, lockedUntil: entry.lockedUntil };
    }
    // the lockout is over: the IP starts with a clean slate
    loginAttempts.delete(ip);
    return { allowed: true, remainingAttempts: loginRateLimit.maxAttempts };
  }
""").replace("""export function checkSSHRateLimit""", """export function resetLoginAttempts(ip: string): void {
  loginAttempts.delete(ip);
}

export function checkSSHRateLimit""")
assert RL_REF.count("resetLoginAttempts") == 1 and "clean slate" in RL_REF and "const locked" in RL_REF
mk("ts3", "ts T3", ["src/lib/utils/rate-limiter.ts"], """
Fix the login limiter in src/lib/utils/rate-limiter.ts. (1) A lockout is cut short: cleanOldAttempts deletes an IP's
entry as soon as all its attempts are older than the 15-minute window, which also throws away the 30-minute
lockedUntil, so a locked-out IP can log in again after 15 minutes. An entry must be kept while its lockout is active,
and checkLoginRateLimit must keep returning allowed: false with the same lockedUntil until the lockout ends.
(2) Once a lockout has expired, the IP starts fresh: its old attempts and lockout are cleared, so it gets the full
5 attempts again even if attempts were recorded during the lockout. Also add an exported function
resetLoginAttempts(ip: string): void that clears an IP's attempts and lockout (called after a successful login).
Do not change the SSH and API limiters or the signature of any existing export.""",
   {"tests/rate-limiter.test.ts": """
import { describe, it, expect, vi, afterEach } from 'vitest';
import { checkLoginRateLimit, recordLoginAttempt, resetLoginAttempts } from '../src/lib/utils/rate-limiter';

const T0 = new Date('2026-01-01T00:00:00Z').getTime();
const MIN = 60 * 1000;

describe('login lockout', () => {
  afterEach(() => { vi.useRealTimers(); });
  it('lasts the full 30 minutes', () => {
    vi.useFakeTimers();
    vi.setSystemTime(T0);
    for (let i = 0; i < 5; i++) recordLoginAttempt('10.0.0.1');
    const first = checkLoginRateLimit('10.0.0.1');
    expect(first.allowed).toBe(false);
    vi.setSystemTime(T0 + 20 * MIN);
    const later = checkLoginRateLimit('10.0.0.1');
    expect(later.allowed).toBe(false);
    expect(later.lockedUntil).toBe(first.lockedUntil);
  });
  it('can be reset after a successful login', () => {
    for (let i = 0; i < 5; i++) recordLoginAttempt('10.0.0.2');
    expect(checkLoginRateLimit('10.0.0.2').allowed).toBe(false);
    resetLoginAttempts('10.0.0.2');
    expect(checkLoginRateLimit('10.0.0.2')).toEqual({ allowed: true, remainingAttempts: 5 });
  });
});
"""},
   {"tests/rate-limiter.hidden.test.ts": """
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as rl from '../src/lib/utils/rate-limiter';

const T0 = new Date('2026-02-01T00:00:00Z').getTime();
const MIN = 60 * 1000;
const lockOut = (ip: string) => { for (let i = 0; i < 5; i++) rl.recordLoginAttempt(ip); return rl.checkLoginRateLimit(ip); };

describe('login limiter hidden', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(T0); });
  afterEach(() => { vi.useRealTimers(); });

  it('locks for exactly 30 minutes', () => {
    const r = lockOut('h1');
    expect(r).toEqual({ allowed: false, remainingAttempts: 0, lockedUntil: T0 + 30 * MIN });
    vi.setSystemTime(T0 + 16 * MIN);
    expect(rl.checkLoginRateLimit('h1')).toEqual(r);
    vi.setSystemTime(T0 + 30 * MIN - 1);
    expect(rl.checkLoginRateLimit('h1').allowed).toBe(false);
  });
  it('starts fresh after the lockout', () => {
    lockOut('h2');
    vi.setSystemTime(T0 + 30 * MIN + 1000);
    expect(rl.checkLoginRateLimit('h2')).toEqual({ allowed: true, remainingAttempts: 5 });
  });
  it('attempts recorded during the lockout do not carry over', () => {
    lockOut('h3');
    vi.setSystemTime(T0 + 29 * MIN);
    for (let i = 0; i < 5; i++) rl.recordLoginAttempt('h3');
    vi.setSystemTime(T0 + 30 * MIN);
    expect(rl.checkLoginRateLimit('h3')).toEqual({ allowed: true, remainingAttempts: 5 });
  });
  it('counts remaining attempts and keeps IPs apart', () => {
    for (let i = 0; i < 4; i++) rl.recordLoginAttempt('h4');
    expect(rl.checkLoginRateLimit('h4')).toEqual({ allowed: true, remainingAttempts: 1 });
    expect(rl.checkLoginRateLimit('h5')).toEqual({ allowed: true, remainingAttempts: 5 });
  });
  it('old attempts still expire after 15 minutes', () => {
    for (let i = 0; i < 4; i++) rl.recordLoginAttempt('h6');
    vi.setSystemTime(T0 + 15 * MIN);
    expect(rl.checkLoginRateLimit('h6')).toEqual({ allowed: true, remainingAttempts: 5 });
  });
  it('reset clears a lockout and is harmless for unknown IPs', () => {
    lockOut('h7');
    rl.resetLoginAttempts('h7');
    rl.resetLoginAttempts('never-seen');
    expect(rl.checkLoginRateLimit('h7')).toEqual({ allowed: true, remainingAttempts: 5 });
  });
  it('leaves the SSH and API limiters alone', () => {
    for (let i = 0; i < 60; i++) rl.recordSSHAttempt('srv');
    expect(rl.checkSSHRateLimit('srv')).toEqual({ allowed: false, remainingAttempts: 0 });
    vi.setSystemTime(T0 + 61 * 1000);
    expect(rl.checkSSHRateLimit('srv')).toEqual({ allowed: true, remainingAttempts: 60 });
    rl.recordAPIAttempt('u1');
    expect(rl.checkAPIRateLimit('u1')).toEqual({ allowed: true, remainingAttempts: 119 });
  });
});
"""},
   {"src/lib/utils/rate-limiter.ts": RL_REF})

# ============ ts4  T2: validateSetting for the settings API ============
SS = (SRC / "src/lib/settings-schema.ts").read_text()
mk("ts4", "ts T2", ["src/lib/settings-schema.ts"], """
Add an exported function validateSetting(key: string, value: unknown): SettingValidation to
src/lib/settings-schema.ts, for the settings API to call before saving a value, and export the type
SettingValidation = { ok: true; value: string | number | boolean } | { ok: false; error: string }. On success the value
is converted to the setting's type; on failure error is a non-empty message. Rules: a key that is not in
EDITABLE_SETTINGS is rejected and the error message contains the key. 'number' settings accept a finite number, or a
string that is a plain decimal number after trimming (for example ' 30 ' or '2.5'); the result must be zero or more
and is returned as a number; '', 'abc', '10s', NaN, Infinity, negative numbers, booleans and null are rejected.
'boolean' settings accept true or false, or the strings 'true' and 'false' in any letter case with surrounding
whitespace, and return a boolean; anything else (including 1, 0 and 'yes') is rejected. 'string' settings accept only
strings; the value is trimmed and an empty result is rejected; when the setting has options, the trimmed value must be
exactly one of them (case-sensitive). Do not change EDITABLE_SETTINGS or EDITABLE_SETTING_KEYS.""",
   {"tests/settings-schema.test.ts": """
import { describe, it, expect } from 'vitest';
import { validateSetting } from '../src/lib/settings-schema';

describe('validateSetting', () => {
  it('converts valid values', () => {
    expect(validateSetting('app.refresh_interval', ' 30 ')).toEqual({ ok: true, value: 30 });
    expect(validateSetting('alerts.enabled', 'TRUE')).toEqual({ ok: true, value: true });
  });
  it('rejects bad values and unknown keys', () => {
    expect(validateSetting('app.theme', 'blue').ok).toBe(false);
    const r = validateSetting('db.password', 'x');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('db.password');
  });
});
"""},
   {"tests/settings-schema.hidden.test.ts": """
import { describe, it, expect } from 'vitest';
import { validateSetting, EDITABLE_SETTINGS, EDITABLE_SETTING_KEYS, type SettingValidation } from '../src/lib/settings-schema';

const ok = (r: SettingValidation) => (r.ok ? r.value : undefined);

describe('validateSetting hidden', () => {
  it.each([
    [42, 42], ['2.5', 2.5], [' 0 ', 0], [0, 0], [3.25, 3.25],
  ])('number %j', (input, out) => {
    expect(validateSetting('ssh.timeout', input)).toEqual({ ok: true, value: out });
  });
  it.each(['', '  ', 'abc', '10s', NaN, Infinity, -1, '-5', true, null, undefined, [], {}])('rejects number %j', (input) => {
    const r = validateSetting('cleanup.audit_log_days', input);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error.length).toBeGreaterThan(0);
  });
  it.each([[true, true], [false, false], ['false', false], [' False ', false], ['tRuE', true]])('boolean %j', (input, out) => {
    expect(validateSetting('alerts.enabled', input)).toEqual({ ok: true, value: out });
  });
  it.each([1, 0, 'yes', 'no', '', null, 'truee'])('rejects boolean %j', (input) => {
    expect(validateSetting('alerts.enabled', input).ok).toBe(false);
  });
  it('strings are trimmed and checked against options', () => {
    expect(validateSetting('app.theme', ' dark ')).toEqual({ ok: true, value: 'dark' });
    expect(validateSetting('app.theme', 'Dark').ok).toBe(false);
    expect(validateSetting('app.timezone', ' America/Chicago ')).toEqual({ ok: true, value: 'America/Chicago' });
    expect(validateSetting('app.timezone', '   ').ok).toBe(false);
    expect(validateSetting('app.timezone', 5).ok).toBe(false);
    expect(validateSetting('app.date_format', true).ok).toBe(false);
  });
  it('every editable key accepts a sensible value', () => {
    for (const def of EDITABLE_SETTINGS) {
      const sample = def.type === 'number' ? 10 : def.type === 'boolean' ? true : def.options ? def.options[0] : 'x';
      expect(ok(validateSetting(def.key, sample))).toBe(sample);
    }
  });
  it('unknown keys name the key and the lists are unchanged', () => {
    const r = validateSetting('servers.secret', 1);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('servers.secret');
    expect(EDITABLE_SETTINGS).toHaveLength(12);
    expect(EDITABLE_SETTING_KEYS).toEqual(EDITABLE_SETTINGS.map(s => s.key));
  });
});
"""},
   {"src/lib/settings-schema.ts": SS.rstrip("\n") + """

export type SettingValidation =
  | { ok: true; value: string | number | boolean }
  | { ok: false; error: string };

/** Checks a value for an editable setting and converts it to the setting's type. */
export function validateSetting(key: string, value: unknown): SettingValidation {
  const def = EDITABLE_SETTINGS.find(s => s.key === key);
  if (!def) return { ok: false, error: `Unknown setting: ${key}` };

  if (def.type === 'number') {
    let n: number;
    if (typeof value === 'number') n = value;
    else if (typeof value === 'string' && /^\\d+(\\.\\d+)?$/.test(value.trim())) n = Number(value.trim());
    else return { ok: false, error: `${key} must be a number` };
    if (!Number.isFinite(n) || n < 0) return { ok: false, error: `${key} must be a number of zero or more` };
    return { ok: true, value: n };
  }

  if (def.type === 'boolean') {
    if (typeof value === 'boolean') return { ok: true, value };
    const s = typeof value === 'string' ? value.trim().toLowerCase() : '';
    if (s === 'true' || s === 'false') return { ok: true, value: s === 'true' };
    return { ok: false, error: `${key} must be true or false` };
  }

  if (typeof value !== 'string') return { ok: false, error: `${key} must be text` };
  const s = value.trim();
  if (!s) return { ok: false, error: `${key} must not be empty` };
  if (def.options && !def.options.includes(s)) {
    return { ok: false, error: `${key} must be one of: ${def.options.join(', ')}` };
  }
  return { ok: true, value: s };
}
"""})

# ============ ts5  T3: multi-GPU nvidia-smi parsing in the shared CommonJS collectors ============
LC = (SRC / "src/lib/linux/collectors.js").read_text()
OLD_GPU = LC[LC.index("    case 'gpu_monitoring': {"):LC.index("    case 'ollama_status': {")]
NEW_GPU = """    case 'gpu_monitoring': {
      const r = await run('nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw --format=csv,noheader 2>/dev/null');
      const none = { name: 'No GPU', vram_total_mb: 0, vram_used_mb: 0, utilization_percent: 0, temperature_c: 0, power_watts: 0 };
      if (r.exitCode !== 0 || !r.stdout.trim()) return { ...none, gpus: [] };
      // [N/A] / [Not Supported] and other non-numbers become 0, never NaN
      const num = (v, parse) => { const n = parse(v || ''); return Number.isFinite(n) ? n : 0; };
      const int = v => num(v, s => parseInt(s, 10));
      const gpus = r.stdout.split('\\n').filter(l => l.trim()).map((line, index) => {
        const parts = line.split(',').map(p => p.trim());
        return {
          index,
          name: parts[0],
          vram_total_mb: int(parts[1]),
          vram_used_mb: int(parts[2]),
          utilization_percent: int(parts[3]),
          temperature_c: int(parts[4]),
          power_watts: num(parts[5], parseFloat),
        };
      });
      const { index, ...first } = gpus[0];
      return { ...first, gpus };
    }

"""
assert OLD_GPU.count("case '") == 1
mk("ts5", "ts T3", ["src/lib/linux/collectors.js"], """
In src/lib/linux/collectors.js (CommonJS, shared by the Next.js widget route and poller.js), make the gpu_monitoring
collector handle machines with several NVIDIA GPUs and unsupported fields. nvidia-smi prints one CSV line per GPU.
Keep the existing top-level fields (name, vram_total_mb, vram_used_mb, utilization_percent, temperature_c,
power_watts) describing the FIRST GPU so existing widgets keep working, and add gpus: an array with one object per
GPU line, in order, each with those same six fields plus index (0-based). A field that nvidia-smi reports as [N/A] or
[Not Supported], or that is otherwise not a number, becomes 0 instead of NaN; names are trimmed; blank lines are
ignored. When nvidia-smi fails or prints nothing, return the existing 'No GPU' object with gpus: []. Do not change
the other collectors or the module's exports.""",
   {"tests/gpu.test.ts": """
import { describe, it, expect } from 'vitest';
import collectors from '../src/lib/linux/collectors.js';

const fake = (stdout: string, exitCode = 0) => async () => ({ stdout, stderr: '', exitCode });

describe('gpu_monitoring', () => {
  it('lists every GPU', async () => {
    const out = 'NVIDIA GeForce RTX 3080 Ti, 16384, 1200, 35, 61, 120.50\\nNVIDIA GeForce RTX 3060, 6144, 300, 5, 45, 30.10\\n';
    const r: any = await collectors.getLinuxWidgetData('gpu_monitoring', fake(out));
    expect(r.name).toBe('NVIDIA GeForce RTX 3080 Ti');
    expect(r.gpus).toHaveLength(2);
    expect(r.gpus[1]).toEqual({ index: 1, name: 'NVIDIA GeForce RTX 3060', vram_total_mb: 6144, vram_used_mb: 300,
      utilization_percent: 5, temperature_c: 45, power_watts: 30.1 });
  });
});
"""},
   {"tests/gpu.hidden.test.ts": """
import { describe, it, expect } from 'vitest';
import collectors from '../src/lib/linux/collectors.js';

const fake = (stdout: string, exitCode = 0) => async () => ({ stdout, stderr: '', exitCode });
const get = (stdout: string, exitCode = 0): Promise<any> => collectors.getLinuxWidgetData('gpu_monitoring', fake(stdout, exitCode));
const NONE = { name: 'No GPU', vram_total_mb: 0, vram_used_mb: 0, utilization_percent: 0, temperature_c: 0, power_watts: 0 };

describe('gpu_monitoring hidden', () => {
  it('single GPU keeps the old top-level shape', async () => {
    const r = await get('NVIDIA RTX 5070 Ti, 16303, 512, 3, 40, 25.00\\n');
    expect(r).toEqual({ name: 'NVIDIA RTX 5070 Ti', vram_total_mb: 16303, vram_used_mb: 512, utilization_percent: 3,
      temperature_c: 40, power_watts: 25,
      gpus: [{ index: 0, name: 'NVIDIA RTX 5070 Ti', vram_total_mb: 16303, vram_used_mb: 512, utilization_percent: 3,
        temperature_c: 40, power_watts: 25 }] });
  });
  it('unsupported fields become 0', async () => {
    const r = await get('Tesla T4, 15360, 0, [N/A], 33, [Not Supported]\\n');
    expect(r.utilization_percent).toBe(0);
    expect(r.power_watts).toBe(0);
    expect(r.gpus[0].power_watts).toBe(0);
    expect(r.temperature_c).toBe(33);
  });
  it('ignores blank lines and keeps order', async () => {
    const r = await get('\\n  A , 1, 2, 3, 4, 5.5\\n\\nB, 10, 20, 30, 40, 50\\n\\n');
    expect(r.gpus.map((g: any) => [g.index, g.name])).toEqual([[0, 'A'], [1, 'B']]);
    expect(r.name).toBe('A');
    expect(r.power_watts).toBe(5.5);
  });
  it('no GPU when nvidia-smi fails or is silent', async () => {
    expect(await get('', 127)).toEqual({ ...NONE, gpus: [] });
    expect(await get('   \\n', 0)).toEqual({ ...NONE, gpus: [] });
  });
  it('other collectors are untouched', async () => {
    const run = async (cmd: string) => ({ stdout: cmd.startsWith('docker') ? 'abc|web|nginx|Up 2h|running|80/tcp\\n' : '', stderr: '', exitCode: 0 });
    expect(await collectors.getLinuxWidgetData('docker_containers', run)).toEqual(
      [{ id: 'abc', name: 'web', image: 'nginx', status: 'Up 2h', state: 'running', ports: '80/tcp' }]);
    expect(Object.keys(collectors)).toEqual(['getLinuxWidgetData']);
  });
});
"""},
   {"src/lib/linux/collectors.js": LC.replace(OLD_GPU, NEW_GPU)})

print("wrote", sorted(p.name for p in C.iterdir()))
