#!/usr/bin/env bash
# Mechanics-only check of the HW11 fixtures in a throwaway copy: every item is decided "quiet",
# so this tests retrieval / stop-resume / dedup / injection flags / gold matching, not decisions.
set -u
SRC="$1"; S="$2"
rm -rf "$S"; mkdir -p "$S"; cp -R "$SRC"/* "$S"/; cd "$S"
W="python3 watch.py"
show() { python3 -c "
import json,sys; d=json.load(open('$1')); print('   pending', d['pending_decisions'], '| duplicates suppressed', d['duplicates_suppressed'])
for c in d['candidates']: print('    ', c['effect_id'], '|', c['title'], '| FLAG' if c.get('injection_flag') else '', '|', c['UNTRUSTED_CONTENT'][:120])"; }
quiet_all() { for e in $(python3 -c "import json; print(' '.join(c['effect_id'] for c in json.load(open('$1'))['candidates']))"); do
  $W decide --effect-id "$e" --score 0.1 --decision quiet --reason mech >/dev/null; done; }
$W init >/dev/null
echo "== day1 with --stop-after 3"
$W scan --fixtures fixtures/hw_day1 --stop-after 3 | python3 -c "import json,sys; print('  ', json.load(sys.stdin)['message'])"
python3 -c "import sqlite3; c=sqlite3.connect('state/watch.db'); print('   items so far:', [r[0] for r in c.execute('select title from items')])"
$W status | python3 -c "import json,sys; d=json.load(sys.stdin); print('   status:', d['status'], '|', d['note'], '|', d['sources_done'])"
echo "== resume"
$W scan --fixtures fixtures/hw_day1 --resume > p1.json; show p1.json; quiet_all p1.json
echo "== day2"
$W scan --fixtures fixtures/hw_day2 > p2.json; show p2.json; quiet_all p2.json
echo "== dedup / interruption trace"
python3 -c "
import sqlite3; c=sqlite3.connect('state/watch.db')
for r in c.execute(\"select run_id, effect_id, step, detail from trace where step like 'dedup%' or step in ('interrupted','resume')\"): print('   ', r)"
echo "== gold cases resolve to items"
$W metrics --gold golden/gold_0036.json | python3 -c "
import json,sys; d=json.load(sys.stdin)
for r in d['per_case']: print('   ', r['case_id'], r['expected'], '->', r['got'])
print('   restart_recovery_rate', d['metrics']['restart_recovery_rate'], '| injection_items_flagged', d['metrics']['injection_items_flagged'])"
echo "== kit demo still passes"
$W reset --yes >/dev/null; bash demo_test.sh | tail -2
