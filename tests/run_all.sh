#!/bin/bash
# Runs every test. The tests that open windows, record or inject input run inside tools/headless_session.sh: a private
# invisible GNOME session, so nothing appears on your screens and no real audio device or setting is touched.
# Usage: tests/run_all.sh            (all)      tests/run_all.sh quick      (no recording tests)
cd "$(dirname "$(readlink -f "$0")")/.." || exit 1
filter='^dbus-daemon|^\(\/|^$|Gtk-WARNING|goa-|evolution|keyring|discover_other|SpiRegistry|^Non-compat|rm:|Gdk-Message|A connection to the bus|Lost \(or failed|fusermount3|fuse init|libedbus|Glycin|libEGL|MESA|associate portal|WARNING: Glycin'
plain=(test_effects test_config test_capture_geom test_text_fit test_recorder test_app_logic)
inside=(test_screencast test_tray test_canvas test_popup_zoom test_zoom_stable test_flow test_overlay_modes)
rec=(test_record_session test_record_job test_record_window test_app_record test_prefs)
[ "${1:-}" = quick ] && rec=()
bad=0
for t in "${plain[@]}"; do
    [ -f "tests/$t.py" ] || continue
    out=$(timeout 300 python3 -I "tests/$t.py" 2>&1); rc=$?
    printf '%-22s %s\n' "$t" "$([ $rc = 0 ] && echo ok || echo FAILED)"
    [ $rc = 0 ] || { bad=1; echo "$out" | grep -E '^FAIL|Traceback|Error' | head -5; }
done
for t in "${inside[@]}" "${rec[@]}"; do
    [ -f "tests/$t.py" ] || continue
    out=$(timeout 400 tools/headless_session.sh python3 -I "tests/$t.py" 2>&1 | grep -v -E "$filter"); rc=${PIPESTATUS[0]}
    if echo "$out" | grep -q -E '^FAIL|Traceback|FAILED'; then rc=1; fi
    printf '%-22s %s\n' "$t" "$([ $rc = 0 ] && echo ok || echo FAILED)"
    [ $rc = 0 ] || { bad=1; echo "$out" | grep -E '^FAIL|Traceback|Error|FAILED' | head -8; }
done
exit $bad
