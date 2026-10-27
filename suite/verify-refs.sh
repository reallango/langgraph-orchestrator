#!/bin/bash
# For each test: the check must FAIL on the base repo and PASS with the reference solution overlaid.
B=${ORCH_B:-~/orch-tests}
IMG=langgraph-orchestrator:orch-test
for t in t1 t2 t3 t4 t5 t6 t7; do
  rm -rf /tmp/vr-$t; cp -r $B/work/$t /tmp/vr-$t
  run_checks() {
    docker run --rm -v /tmp/vr-$t:/w -w /w -v $B/spec/$t/check.txt:/check.txt:ro $IMG \
      bash -c 'rc=0; while IFS= read -r l; do [ -z "$l" ] && continue; sh -c "$l" >/tmp/o 2>&1 || { rc=1; echo "   [fail] ${l:0:70}"; tail -n 3 /tmp/o | cut -c1-160 | sed "s/^/     /"; }; done < /check.txt; exit $rc'
  }
  echo "== $t base (expect FAIL)"; run_checks >/tmp/base.out 2>&1 && echo "   !! base PASSES: test is broken" || echo "   ok: fails as expected"
  cp -r $B/ref/$t/. /tmp/vr-$t/
  echo "== $t reference (expect PASS)"; run_checks && echo "   ok: passes" || echo "   !! reference FAILS: test is broken"
  docker run --rm -v /tmp:/t $IMG rm -rf /t/vr-$t
done
