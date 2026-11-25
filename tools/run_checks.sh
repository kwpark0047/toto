#!/bin/sh
# 로컬 점검용: 임시 DB로 서버를 띄우고 테스트 3종을 돌린 뒤 서버를 내린다.
set -e
cd "$(dirname "$0")/.."
TMP=/workspace/.tmp-test
mkdir -p "$TMP"
DB="$TMP/run.db"
PORT="${PORT:-8050}"
rm -f "$DB" "$DB"-wal "$DB"-shm
MENU_DB="$DB" python3 server.py --port "$PORT" --reset > "$TMP/server.log" 2>&1 &
SRV=$!
sleep 2
set +e
python3 tools/smoke_test.py "http://127.0.0.1:$PORT" > "$TMP/smoke.log" 2>&1
SMOKE=$?
MENU_DB="$DB" python3 tools/dom_harness.py "http://127.0.0.1:$PORT" > "$TMP/dom.log" 2>&1
DOM=$?
python3 tools/check_pages.py > "$TMP/pages.log" 2>&1
PAGES=$?
kill "$SRV" 2>/dev/null
sleep 1
echo "smoke=$SMOKE dom=$DOM pages=$PAGES"
grep -E "통과 |실패 항목|❌" "$TMP/smoke.log" | head -40
echo "--- dom ---"
tail -25 "$TMP/dom.log"
echo "--- pages ---"
tail -10 "$TMP/pages.log"
echo "--- server tracebacks: $(grep -c Traceback "$TMP/server.log") ---"
grep -A10 Traceback "$TMP/server.log" | head -40
