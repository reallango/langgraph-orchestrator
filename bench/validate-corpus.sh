#!/bin/bash
# For every task: visible check FAILS on base; visible AND hidden PASS on reference; hidden FAILS on base.
C=${CORPUS:-$HOME/orch-bench/corpus}
IMG=${IMG:-langgraph-orchestrator:orch-test}
run_lines() {  # dir file
  docker run --rm -v "$1":/w -w /w -v "$2":/cmds:ro $IMG bash -c '
    git config --global --add safe.directory "*" >/dev/null 2>&1
    rc=0; while IFS= read -r l; do [ -z "$l" ] && continue
      sh -c "$l" >/tmp/o 2>&1 || { rc=1; echo "   [fail] ${l:0:80}"; tail -n 4 /tmp/o | cut -c1-170 | sed "s/^/       /"; }
    done < /cmds; exit $rc'
}
prep() {  # task variant(base|ref) -> /tmp/vc-<t>-<variant> with git repo, hidden files NOT included
  rm -rf /tmp/vc-$1-$2; mkdir -p /tmp/vc-$1-$2; cp -r $C/$1/base/. /tmp/vc-$1-$2/
  [ "$2" = ref ] && cp -r $C/$1/ref/. /tmp/vc-$1-$2/
  (cd /tmp/vc-$1-$2 && git init -q -b main && git add -A && git -c user.name=t -c user.email=t@t commit -qm base)
}
bad=0
for t in $(ls $C | sort -V); do
  echo "== $t ($(cat $C/$t/meta.txt))"
  prep $t base; prep $t ref
  run_lines /tmp/vc-$t-base $C/$t/check.txt >/dev/null 2>&1 && { echo "   !! visible PASSES on base"; bad=1; } || echo "   ok: visible fails on base"
  out=$(run_lines /tmp/vc-$t-ref $C/$t/check.txt) && echo "   ok: visible passes on ref" || { echo "   !! visible FAILS on ref"; echo "$out"; bad=1; }
  cp -r $C/$t/hidden/. /tmp/vc-$t-ref/
  out=$(run_lines /tmp/vc-$t-ref $C/$t/hidden.txt) && echo "   ok: hidden passes on ref" || { echo "   !! hidden FAILS on ref"; echo "$out"; bad=1; }
  cp -r $C/$t/hidden/. /tmp/vc-$t-base/
  run_lines /tmp/vc-$t-base $C/$t/hidden.txt >/dev/null 2>&1 && { echo "   !! hidden PASSES on base"; bad=1; } || echo "   ok: hidden fails on base"
  docker run --rm -v /tmp:/t $IMG sh -c "rm -rf /t/vc-$t-base /t/vc-$t-ref"
done
[ $bad = 0 ] && echo "ALL CORPUS CHECKS VALID" || echo "SOME CHECKS INVALID"
