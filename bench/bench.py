#!/usr/bin/env python3
"""Autonomous model/config tournament for the local plan/code/review pipeline. Resumable: re-running continues.

Layout (all under ~/orch-bench):  corpus/  work/  runs/  results.jsonl  state.json  STATE.md  prep.json  bench.log
Run:  nohup python3 bench.py > bench.out 2>&1 &
Env:  BENCH_SOFT_HOURS (default 12)  BENCH_HARD_HOURS (default 19)  BENCH_SMOKE=1 (tiny dry run)
"""
import hashlib, json, os, re, shutil, subprocess, sys, threading, time, urllib.request
from collections import defaultdict
from pathlib import Path

B = Path(os.environ.get("BENCH_DIR", Path.home() / "orch-bench"))
REAL = Path.home() / "orch-bench"
CORPUS, WORK, RUNS, PULLS = REAL / "corpus", B / "work", B / "runs", REAL / "pulls"
RESULTS, STATE, PREP, LOG, STATE_MD = B / "results.jsonl", B / "state.json", B / "prep.json", B / "bench.log", B / "STATE.md"
IMG = os.environ.get("BENCH_IMAGE", "langgraph-orchestrator:orch-test")
CODE = Path.home() / "orch-dev" / "orch"
HOSTS = {"gamebed": "http://192.168.1.171:11434", "big131": "http://192.168.1.131:11434",
         "atomeve": "http://192.168.1.15:11434"}
SMOKE = os.environ.get("BENCH_SMOKE") == "1"
B.mkdir(parents=True, exist_ok=True)
_t0 = B / "t0"
if not _t0.exists():
    _t0.write_text(str(time.time()))
T0 = float(_t0.read_text())          # persisted so restarts do not extend the deadlines
SOFT = T0 + float(os.environ.get("BENCH_SOFT_HOURS", "13")) * 3600
HARD = T0 + float(os.environ.get("BENCH_HARD_HOURS", "19")) * 3600
SCREEN = ["t1", "t2", "t3", "t8", "t9", "t10", "t6"]                       # screening subset (easy -> harder)
FULL = ["t1", "t2", "t8", "t3", "t9", "t10", "t4", "t5", "t6", "t11", "t12", "t7", "t13"]
if SMOKE:
    SCREEN, FULL = ["t1"], ["t1"]

SMALL_MODELS = ["qwen2.5-coder:7b", "qwen3.5:4b", "ornith:9b", "granite4.2:8b", "lfm2.5:8b", "qwen3.5:9b", "gemma4:e4b"]
BIG_CODERS = ["qwen2.5-coder:14b", "gpt-oss:20b", "gemma4:12b", "qwen3.5:27b", "qwen3.6:35b-a3b", "ornith:35b",
              "nemotron-3.5-lightning:30b", "gemma4:26b", "muse-glimmer:30b", "granite4.2:30b", "qwen3:14b"]
BIG_REASONERS = ["deepseek-r1:14b", "qwen3:14b", "gpt-oss:20b", "gemma4:12b"]
if SMOKE:
    SMALL_MODELS, BIG_CODERS, BIG_REASONERS = ["qwen2.5-coder:7b"], ["qwen2.5-coder:14b"], ["qwen3:14b"]

PAUSE, PAUSE_NOW = REAL / "PAUSE", REAL / "PAUSE_NOW"   # touch PAUSE: no new jobs start; PAUSE_NOW: in-flight results are discarded (re-run later)
PAUSED_S = 0.0     # total seconds spent paused in this process (later stages' deadlines shift by it)
lock = threading.RLock()


def log(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with lock, LOG.open("a") as f:
        f.write(line + "\n")


def jload(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def jsave(p, obj):
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1))
    tmp.replace(p)


def http(method, url, body=None, timeout=60):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def sh(cmd, timeout=None, **kw):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


# ---------------------------------------------------------------- models / prep
_tags_cache = {}


def host_tags(host, fresh=False):
    c = _tags_cache.get(host)
    if c and not fresh and time.time() - c[0] < 25:
        return c[1]
    try:
        tags = {m["name"]: m for m in http("GET", HOSTS[host] + "/api/tags", timeout=8)["models"]}
    except Exception:
        tags = {}
    _tags_cache[host] = (time.time(), tags)
    return tags


def has_model(host, tag):
    t = host_tags(host)
    return tag in t or tag + ":latest" in t


def pull_failed(tag):
    for p in PULLS.glob("*.log"):
        if re.search(rf"FAIL\s+{re.escape(tag)}(\s|$)", p.read_text()):
            return True
    return False


def variant_name(tag):
    return "bench-" + re.sub(r"[^a-z0-9]+", "-", tag.lower()).strip("-")


def prep_info():
    return jload(PREP, {})


def prep_key(host, tag):
    return f"{host}|{tag}"


def prep_model(host, tag):
    """Create a bench variant (fixed ctx / num_predict, GPU-pinned when it should fit) and measure speed and fit."""
    url, var = HOSTS[host], variant_name(tag)
    info = {"host": host, "tag": tag, "variant": var, "ok": False}
    try:
        show = http("POST", url + "/api/show", {"model": tag}, timeout=60)
        caps = show.get("capabilities", [])
        meta = host_tags(host, fresh=True).get(tag) or host_tags(host).get(tag + ":latest") or {}
        size_gb = meta.get("size", 0) / 1e9
        thinking = "thinking" in caps
        info.update(thinking=thinking, size_gb=round(size_gb, 1), caps=caps)
        limit = 5.4 if host == "gamebed" else 13.0
        ctx = 12288 if host == "gamebed" else 16384
        for forced in ([True, False] if size_gb <= limit else [False]):
            params = {"num_ctx": ctx, "num_predict": 8192 if thinking else 3072}
            if forced:
                params["num_gpu"] = 99
            http("POST", url + "/api/create", {"model": var, "from": tag, "parameters": params, "stream": False}, timeout=300)
            t = time.time()
            try:
                # first call loads the weights (mmap'd, so the first decode is slow); measure the second one
                r0 = http("POST", url + "/api/generate", {"model": var, "prompt": "Say hi.", "stream": False,
                                                          "options": {"num_predict": 24}}, timeout=900)
                r = http("POST", url + "/api/generate", {"model": var, "prompt": "Write a Python function add(a, b). Code only.",
                                                         "stream": False, "options": {"num_predict": 300}}, timeout=900)
                r["load_duration"] = r0.get("load_duration", 0)
            except Exception as e:
                log(f"prep {host} {tag} forced={forced} failed: {e}")
                continue
            ps = [m for m in http("GET", url + "/api/ps", timeout=15).get("models", []) if m["name"].startswith(var)]
            gpu_frac = round(ps[0]["size_vram"] / ps[0]["size"], 2) if ps and ps[0].get("size") else None
            tps = round(r.get("eval_count", 0) / max(r.get("eval_duration", 1) / 1e9, 1e-6), 1)
            info.update(ok=True, forced=forced, ctx=ctx, tps=tps, load_s=round(r.get("load_duration", 0) / 1e9, 1),
                        gpu_frac=gpu_frac, prep_s=round(time.time() - t), too_slow=tps < 3.0)
            break
    except Exception as e:
        info["error"] = str(e)[:300]
    with lock:
        P = prep_info()
        P[prep_key(host, tag)] = info
        jsave(PREP, P)
    log(f"prep {host} {tag}: " + json.dumps({k: info.get(k) for k in ("ok", "forced", "tps", "gpu_frac", "size_gb", "thinking", "too_slow", "error")}))
    return info


# ---------------------------------------------------------------- jobs
class Job:
    hosts = ()

    def __init__(self, jid):
        self.id = jid

    def ready(self):
        return True

    def run(self):
        pass


class Prep(Job):
    def __init__(self, host, tag):
        super().__init__(f"prep:{host}:{tag}")
        self.host, self.tag, self.hosts = host, tag, (host,)

    def done(self):
        return prep_key(self.host, self.tag) in prep_info()

    def ready(self):
        return has_model(self.host, self.tag) or pull_failed(self.tag)

    def run(self):
        if not has_model(self.host, self.tag):
            with lock:
                P = prep_info()
                P[prep_key(self.host, self.tag)] = {"host": self.host, "tag": self.tag, "ok": False, "error": "pull failed"}
                jsave(PREP, P)
            return
        prep_model(self.host, self.tag)


def cfg(name, coder, reasoner=None, repair=None, planner=True, reviewer=True, diagnose=False, edit="diff", repairs=2,
        hints=False, verify=False, cascade=None, attempt_repairs=1, max_total=8, solvers=None):
    return {"name": name, "coder": coder, "reasoner": reasoner, "repair": repair, "edit": edit, "repairs": repairs,
            "hints": hints, "verify": verify, "cascade": list(cascade or []), "attempt_repairs": attempt_repairs,
            "max_total": max_total, "solvers": list(solvers or []),
            "planner": planner and reasoner is not None, "reviewer": reviewer and reasoner is not None,
            "diagnose": diagnose and reasoner is not None}


def role_ok(role):
    if role is None:
        return True
    info = prep_info().get(prep_key(*role))
    return bool(info and info.get("ok"))


def role_variant(role):
    return variant_name(role[1]), HOSTS[role[0]]


def done_ids():
    ids = set()
    if RESULTS.exists():
        for line in RESULTS.read_text().splitlines():
            try:
                ids.add(json.loads(line)["job"])
            except Exception:
                pass
    return ids


class Task(Job):
    def __init__(self, phase, config, task, rep=1):
        super().__init__(f"{phase}:{config['name']}:{task}:r{rep}")
        self.phase, self.config, self.task, self.rep = phase, config, task, rep
        roles = ([r for r in (config["coder"], config["reasoner"], config["repair"]) if r]
                 + list(config.get("cascade", [])) + list(config.get("solvers", [])))
        self.hosts = tuple(sorted({r[0] for r in roles}))
        self.roles = roles
        self.safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", self.id)[:70] + "_" + hashlib.sha1(self.id.encode()).hexdigest()[:8]

    def ready(self):
        return all(role_ok(r) for r in self.roles)

    def dead(self):
        """A role's model is known to be unusable (pull failed, would not load, or far too slow for screening)."""
        P = prep_info()
        for r in self.roles:
            info = P.get(prep_key(*r))
            if info is not None and (not info.get("ok") or (info.get("too_slow") and self.phase != "P3")):
                return True
        return False

    def run(self):
        for h in self.hosts:  # a worker that is down: wait a while instead of burning the job
            for _ in range(60):
                if host_tags(h, fresh=True):
                    break
                time.sleep(30)
        row = run_task_job(self)
        if PAUSE_NOW.exists():  # killed by an immediate pause: do not record, it will be re-run on resume
            log(f"DISCARDED (pause --now) {self.id}")
            return
        with lock, RESULTS.open("a") as f:
            f.write(json.dumps(row) + "\n")
        update_state_md()
        log(f"DONE {self.id} status={row['status']} true_pass={row['true_pass']} t={row['elapsed']}s cyc={row.get('cycles')} labels={row['labels']}")


def read_cmds(p):
    return [l for l in Path(p).read_text().splitlines() if l.strip()]


def run_task_job(job):
    t0 = time.time()
    c, task = job.config, job.task
    tdir = CORPUS / task
    repo = WORK / job.safe / "repo"
    if repo.parent.exists():
        subprocess.run(["docker", "run", "--rm", "-v", f"{WORK}:/w", IMG, "rm", "-rf", f"/w/{job.safe}"])
    repo.mkdir(parents=True)
    shutil.copytree(tdir / "base", repo, dirs_exist_ok=True)
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"],
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"]):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    env = {"ORCH_DIRECT": "1", "ORCH_RUNS_DIR": "/runs", "ORCH_AIDER_TIMEOUT": "600", "ORCH_CHECK_TIMEOUT": "240",
           "ORCH_LLM_TIMEOUT": "900", "ORCH_MAX_REPAIRS": str(c.get("repairs", 2)),
           "ORCH_EDIT_FORMAT": c.get("edit", "diff"),
           "ORCH_HINTS": "1" if c.get("hints") else "0", "ORCH_VERIFY": "1" if c.get("verify") else "0",
           "ORCH_ATTEMPT_REPAIRS": str(c.get("attempt_repairs", 1)), "ORCH_MAX_TOTAL": str(c.get("max_total", 8)),
           "ORCH_CASCADE_CODERS": json.dumps([list(role_variant(r)) for r in c.get("cascade", [])]) if c.get("cascade") else "",
           "ORCH_SOLVERS": json.dumps([list(role_variant(r)) for r in c.get("solvers", [])]) if c.get("solvers") else "",
           "ORCH_PLANNER": "1" if c["planner"] else "0", "ORCH_REVIEWER": "1" if c["reviewer"] else "0",
           "ORCH_DIAGNOSE": "1" if c["diagnose"] else "0",
           "ORCH_CODER_CANDIDATES": json.dumps([list(role_variant(c["coder"]))]),
           "ORCH_REPAIR_CODER_CANDIDATES": json.dumps([list(role_variant(c["repair"] or c["coder"]))]),
           "ORCH_REASONER_CANDIDATES": json.dumps([list(role_variant(c["reasoner"]))] if c["reasoner"] else [["none", HOSTS["gamebed"]]]),
           "LITELLM_API_KEY": "ollama"}
    env.update(c.get("env") or {})   # per-config overrides (e.g. a simulated dead host)
    cmd =["docker", "run", "--rm", "--name", "orchbench-" + job.safe[-60:]]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    files = (tdir / "edit.txt").read_text().split()
    cmd += ["-v", f"{WORK}:/app", "-v", f"{RUNS}:/runs", "-v", f"{CODE}:/opt/orch/orch:ro", IMG,
            "python", "-m", "orch", "run", "--repo", f"/app/{job.safe}/repo", "--task", (tdir / "task.txt").read_text().strip()]
    for line in read_cmds(tdir / "check.txt"):
        cmd += ["--check", line]
    if files:
        cmd += ["--files", *files]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=40 * 60)
        rc, out, err = p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", "TIMEOUT"
        sh(["docker", "kill", "orchbench-" + job.safe[-60:]])
    try:
        meta = json.loads(out[out.index("{"): out.rindex("}") + 1])
    except Exception:
        meta = {"status": "error", "reason": f"unparseable output rc={rc}: {(out + err)[-300:]}"}
    sh(["docker", "run", "--rm", "-v", f"{WORK}:/app", "-v", f"{RUNS}:/runs", IMG, "chown", "-R", f"{os.getuid()}:{os.getgid()}", "/app", "/runs"])
    return build_row(job, meta, t0, rc)


SCORE_SH = r'''
cp -r "$WT" /tmp/s 2>/dev/null || { echo "VIS=0 HID=0 NOWT=1"; exit 0; }
cd /tmp/s
run() { rc=0; while IFS= read -r l; do [ -z "$l" ] && continue; sh -c "$l" >/dev/null 2>&1 || rc=1; done < "$1"; echo $rc; }
v=$(run /task/check.txt)
cp -r /task/hidden/. /tmp/s/
h=$(run /task/hidden.txt)
echo "VIS=$((1-v)) HID=$((1-h))"
'''


def score_worktree(job, run_id):
    wt = f"/runs/{run_id}/work"
    rc, out = sh(["docker", "run", "--rm", "-e", f"WT={wt}", "-v", f"{WORK}:/app", "-v", f"{RUNS}:/runs",
                  "-v", f"{CORPUS / job.task}:/task:ro", IMG, "bash", "-c", SCORE_SH], timeout=900)
    m = re.search(r"VIS=(\d) HID=(\d)", out)
    return (m.group(1) == "1", m.group(2) == "1") if m else (False, False)


def build_row(job, meta, t0, rc):
    rid = meta.get("id")
    rdir = RUNS / rid if rid else None
    phases, tokens, labels, final_files = defaultdict(float), [0, 0], [], {}
    if rdir and rdir.exists():
        ev = []
        for line in (rdir / "events.jsonl").read_text().splitlines() if (rdir / "events.jsonl").exists() else []:
            try:
                ev.append(json.loads(line))
            except Exception:
                pass
        for a, b in zip(ev, ev[1:]):
            phases[b["kind"]] += b["t"] - a["t"]
        for f in rdir.glob("*aider-output-c*.txt"):
            for s, r in re.findall(r"Tokens: ([\d.]+k?) sent, ([\d.]+k?) received", f.read_text(errors="replace")):
                tokens[0] += _num(s)
                tokens[1] += _num(r)
            if "TIMEOUT after" in f.read_text(errors="replace")[:200]:
                labels.append("aider_timeout")
    vis, hid = (False, False)
    if rid and (rdir / "work").exists():
        vis, hid = score_worktree(job, rid)
        labels += classify(job, rdir, meta, vis, hid)
    elif meta.get("status") == "error":
        labels.append("infra_or_crash")
    status = meta.get("status", "error")
    true_pass = bool(vis and hid)
    if status == "passed" and not true_pass:
        labels.append("false_pass")
    if status != "passed" and true_pass:
        labels.append("false_fail")
    return {"job": job.id, "phase": job.phase, "config": job.config["name"], "task": job.task, "rep": job.rep,
            "status": status, "reason": (meta.get("reason") or "")[:200], "cycles": meta.get("cycles"),
            "visible_ok": vis, "hidden_ok": hid, "true_pass": true_pass, "elapsed": round(time.time() - t0),
            "phase_s": {k: round(v) for k, v in phases.items()}, "tokens_sent": tokens[0], "tokens_recv": tokens[1],
            "run": rid, "labels": sorted(set(labels)), "tier": (CORPUS / job.task / "meta.txt").read_text().split()[1],
            "lang": (CORPUS / job.task / "meta.txt").read_text().split()[0], "ts": time.time()}


def _num(s):
    return float(s[:-1]) * 1000 if s.endswith("k") else float(s)


DEF = re.compile(r"^\s*(?:def|function|class)\s+([\w-]+)", re.M)


def classify(job, rdir, meta, vis, hid):
    labels = []
    reason = meta.get("reason", "")
    if "repeated" in reason:
        labels.append("stuck_repeat")
    if "no changes" in reason:
        labels.append("no_changes")
    if "valid JSON" in reason:
        labels.append("bad_json")
    if meta.get("status") == "escalated":
        labels.append("escalated")
    try:
        text = "\n".join(p.read_text(errors="replace") for p in sorted(rdir.glob("*checks-c*.txt"))[-1:])
        if re.search(r"SyntaxError|ParserError|ParseException|ParentContainsErrorRecordException|Unexpected token", text):
            labels.append("syntax_error")
    except Exception:
        pass
    try:  # deleted existing definitions
        base_names = set()
        for p in (CORPUS / job.task / "base").rglob("*"):
            if p.is_file() and p.suffix in (".py", ".ps1") and "test" not in p.name.lower():
                base_names |= set(DEF.findall(p.read_text(errors="replace")))
        final_names = set()
        for p in (rdir / "work").rglob("*"):
            if p.is_file() and p.suffix in (".py", ".ps1") and ".git" not in p.parts:
                final_names |= set(DEF.findall(p.read_text(errors="replace")))
        if base_names - final_names:
            labels.append("deleted_code")
    except Exception:
        pass
    if vis and not hid:
        labels.append("overfit_visible")
    return labels


# ---------------------------------------------------------------- scheduler
def run_jobs(jobs, deadline, name):
    done = done_ids()
    pending = [j for j in jobs if (j.id not in done if isinstance(j, Task) else not j.done())]
    log(f"== {name}: {len(pending)} jobs pending ({len(jobs) - len(pending)} already done)")
    busy, threads, cv = set(), [], threading.Condition()

    def work(job):
        try:
            job.run()
        except Exception as e:
            log(f"JOB ERROR {job.id}: {type(e).__name__}: {e}")
        finally:
            with cv:
                busy.difference_update(job.hosts)
                cv.notify_all()

    while pending:
        if PAUSE.exists():
            t_p = time.time()
            log("PAUSED: no new jobs will start (run ~/orch-bench/resume.sh to continue)")
            while PAUSE.exists():
                time.sleep(15)
            global PAUSED_S
            PAUSED_S += time.time() - t_p
            deadline += time.time() - t_p   # paused time does not eat the budget
            log("RESUMED")
            continue
        dead = [j for j in pending if isinstance(j, Task) and j.dead()]
        if dead:
            log(f"== {name}: dropping {len(dead)} jobs whose model is unusable ({sorted({d.config['name'] for d in dead})[:4]})")
            pending = [j for j in pending if j not in dead]
            continue
        if time.time() > min(deadline, HARD):
            log(f"== {name}: deadline reached, dropping {len(pending)} jobs")
            break
        with cv:
            pick = next((j for j in pending if not (set(j.hosts) & busy) and j.ready()), None)
            if pick is None:
                if not busy and all(not j.ready() for j in pending):
                    # nothing running and nothing can become ready (failed pulls etc.): wait a bit, then give up on them
                    stuck = [j for j in pending if not j.ready()]
                    if time.time() - getattr(run_jobs, "_idle_since", time.time()) > 1800:
                        log(f"== {name}: giving up on {len(stuck)} jobs that never became ready")
                        break
                    run_jobs._idle_since = getattr(run_jobs, "_idle_since", time.time())
                cv.wait(timeout=20)
                continue
            run_jobs._idle_since = time.time()
            pending.remove(pick)
            busy.update(pick.hosts)
        t = threading.Thread(target=work, args=(pick,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    log(f"== {name}: finished")


# ---------------------------------------------------------------- analysis
def load_rows():
    rows = []
    if RESULTS.exists():
        for line in RESULTS.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def by_config(rows, prefix=""):
    d = defaultdict(list)
    for r in rows:
        if r["config"].startswith(prefix):
            d[r["config"]].append(r)
    return d


def rank(rows, prefix, min_jobs=None):
    min_jobs = min(3, len(SCREEN)) if min_jobs is None else min_jobs
    out = []
    for name, rs in by_config(rows, prefix).items():
        if len(rs) < min_jobs:
            continue
        tp = sum(r["true_pass"] for r in rs) / len(rs)
        out.append((tp, -sum(r["elapsed"] for r in rs) / len(rs), name))
    return [n for _, _, n in sorted(out, reverse=True)]


def ranked(rows, prefix, tol=1, min_jobs=None):
    """Selection order: the FASTEST config among those within `tol` true passes of the best, then the rest by passes.
    (Pass counts on a handful of tasks are noisy, and a model that is 6x slower for one extra pass is not a better pick.)"""
    min_jobs = min(3, len(SCREEN)) if min_jobs is None else min_jobs
    stats = []
    for name, rs in by_config(rows, prefix).items():
        if len(rs) >= min_jobs:
            stats.append((sum(r["true_pass"] for r in rs), sum(r["elapsed"] for r in rs) / len(rs), name))
    if not stats:
        return []
    top = max(s[0] for s in stats)
    best = min((s for s in stats if s[0] == top), key=lambda s: s[1])
    # prefer a config within `tol` passes only when it is materially (>= 1.5x) faster than the top scorer
    faster = [s for s in stats if s[0] >= top - tol and s[1] * 1.5 <= best[1]]
    if faster:
        best = min(faster, key=lambda s: s[1])
    rest = sorted((s for s in stats if s is not best), key=lambda s: (-s[0], s[1]))
    return [best[2]] + [s[2] for s in rest]


def tag_of(config_name):
    parts = config_name.split("|")
    return parts[2] if len(parts) > 2 else config_name


def update_state_md():
    with lock:
        rows = load_rows()
        st = jload(STATE, {})
        lines = ["# Benchmark state (auto-generated)", "",
                 f"updated: {time.strftime('%F %T')}  elapsed: {(time.time() - T0) / 3600:.1f}h of soft {(SOFT - T0) / 3600:.0f}h / hard {(HARD - T0) / 3600:.0f}h",
                 f"phase: {st.get('phase', '?')}   jobs done: {len(rows)}   true-pass so far: {sum(r['true_pass'] for r in rows)}",
                 "", "Goal: find the best model combination for plan/code/review on local GPUs (3080Ti .131 16GB, game-bed .171 6GB;",
                 "AtomEve offline by design). Resume: `cd ~/orch-bench && nohup python3 bench.py > bench.out 2>&1 &` (continues from results.jsonl).",
                 "Report: `python3 report.py` -> report.md.  Selections so far:", "```", json.dumps(st.get("picks", {}), indent=1), "```", "",
                 "| config | n | true-pass | orch-pass | avg s |", "|---|---|---|---|---|"]
        for name, rs in sorted(by_config(rows).items()):
            lines.append(f"| {name} | {len(rs)} | {sum(r['true_pass'] for r in rs)} | {sum(r['status'] == 'passed' for r in rs)} | {sum(r['elapsed'] for r in rs) // len(rs)} |")
        STATE_MD.write_text("\n".join(lines))
        (B / "status.json").write_text(json.dumps({"phase": st.get("phase"), "done": len(rows), "t": time.time(),
                                                   "elapsed_h": round((time.time() - T0) / 3600, 2)}))


def set_phase(name, **picks):
    st = jload(STATE, {})
    st["phase"] = name
    st.setdefault("picks", {}).update(picks)
    jsave(STATE, st)
    log(f"##### PHASE {name} {json.dumps(picks) if picks else ''}")
    update_state_md()


# ---------------------------------------------------------------- tournament
def models_on(host, tags):
    return [(host, t) for t in tags]


def main():
    for d in (WORK, RUNS):
        d.mkdir(exist_ok=True)
    st = jload(STATE, {})
    if st.get("phase") in ("DONE",) or str(st.get("phase", "")).startswith("ABORTED"):
        log(f"already finished ({st.get('phase')}); nothing to do")
        return
    log(f"bench start smoke={SMOKE} soft={SOFT - T0:.0f}s hard={HARD - T0:.0f}s picks={st.get('picks')}")

    # ---- P1: coder-only screening (no planner/reviewer): which models can edit code on their own?
    set_phase("P1 coder screening")
    preps = [Prep("gamebed", t) for t in SMALL_MODELS] + [Prep("big131", t) for t in sorted(set(BIG_CODERS + BIG_REASONERS), key=lambda x: (x not in BIG_CODERS, x))]
    jobs = []
    for role in models_on("gamebed", SMALL_MODELS) + models_on("big131", BIG_CODERS):
        for t in SCREEN:
            jobs.append(Task("P1", cfg(f"P1|{role[0]}|{role[1]}", coder=role, planner=False, reviewer=False), t))
    # interleave preps first so the scheduler can start as soon as the baseline models are ready
    run_jobs(preps + jobs, min(SOFT, T0 + 3.5 * 3600), "P1")

    rows = load_rows()
    small_rank = [tag_of(n) for n in ranked(rows, "P1|gamebed|")]
    big_rank = [tag_of(n) for n in ranked(rows, "P1|big131|")]
    if not small_rank or not big_rank:
        log("P1 produced no usable ranking; stopping")
        set_phase("ABORTED: no P1 ranking")
        return
    best_small, best_big = small_rank[0], big_rank[0]
    set_phase("P2 reasoner screening", best_small=best_small, best_big=best_big, small_rank=small_rank, big_rank=big_rank)

    # ---- P2: which reasoner (planner+reviewer) helps? big ones on .131 feeding the small coder; small ones on game-bed
    reasoners = list(dict.fromkeys(BIG_REASONERS + big_rank[:2]))[:5]
    others = [t for t in small_rank if t != best_small][:2]
    p2_tasks = SCREEN[:5]
    jobs = []
    for tag in reasoners:
        for t in p2_tasks:
            jobs.append(Task("P2", cfg(f"P2|R131|{tag}|{best_small}", coder=("gamebed", best_small), reasoner=("big131", tag)), t))
    for tag in [best_small] + others:
        for t in p2_tasks:
            jobs.append(Task("P2", cfg(f"P2|Rgb|{tag}|{best_small}", coder=("gamebed", best_small), reasoner=("gamebed", tag)), t))
    run_jobs(jobs, min(SOFT, time.time() + 3 * 3600), "P2")

    rows = load_rows()
    r131 = [tag_of(n) for n in ranked(rows, "P2|R131|")]
    rgb = [tag_of(n) for n in ranked(rows, "P2|Rgb|")]
    best_reasoner = r131[0] if r131 else best_big
    best_small_reasoner = rgb[0] if rgb else best_small
    set_phase("P3 full comparison", best_reasoner=best_reasoner, best_small_reasoner=best_small_reasoner, r131_rank=r131, rgb_rank=rgb)

    # ---- P3: full corpus on the finalist architectures
    sc, bc = ("gamebed", best_small), ("big131", best_big)
    rs, rsm = ("big131", best_reasoner), ("gamebed", best_small_reasoner)
    finals = [
        cfg("F3 reasoner131+small coder", coder=sc, reasoner=rs),
        cfg("F1 small coder only", coder=sc, planner=False, reviewer=False),
        cfg("F5 F3+escalate to big coder", coder=sc, reasoner=rs, repair=bc),
        cfg("F8 small-only (gamebed alone)", coder=sc, reasoner=rsm),
        cfg("F7a big-only self-reasoner", coder=bc, reasoner=bc),
        cfg("F4 F3+diagnose", coder=sc, reasoner=rs, diagnose=True),
        cfg("F2 big coder only", coder=bc, planner=False, reviewer=False),
        cfg("F7b big-only split", coder=bc, reasoner=rs),
        cfg("F6 F5+diagnose", coder=sc, reasoner=rs, repair=bc, diagnose=True),
    ]
    if SMOKE:
        finals = finals[:3]
    jobs = [Task("P3", c, t) for c in finals for t in FULL]
    run_jobs(jobs, SOFT, "P3 rep1")

    # ---- P4: extra repetitions for the leading configs while budget remains (variance estimate)
    for rep in (2, 3):
        if time.time() > SOFT - 40 * 60:
            break
        rows = load_rows()
        top = rank([r for r in rows if r["phase"] == "P3"], "", min_jobs=len(FULL))[:3]
        set_phase(f"P4 repetition {rep}", top3=top)
        cmap = {c["name"]: c for c in finals}
        jobs = [Task("P3", cmap[n], t, rep) for t in FULL for n in top if n in cmap]
        run_jobs(jobs, SOFT, f"P4 rep{rep}")

    set_phase("DONE")
    sh([sys.executable, str(B / "report.py")])
    log("bench complete")


if __name__ == "__main__":
    main()
