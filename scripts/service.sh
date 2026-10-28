#!/bin/zsh
# Local lifecycle helper. Installation is an explicit user action, never run by the API.
set -eu
umask 077
PROJECT_DIR="${0:A:h:h}"
LABEL="com.ultron.adb-qa"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
COMMAND="${1:-status}"
case "$COMMAND" in
  install)
    MODE="${2:-mock}"
    if [[ "$MODE" != mock && "$MODE" != real ]]; then
      print -u2 '模式必須為 mock 或 real'; exit 1
    fi
    PYTHON_BIN="$(command -v python3)"
    mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/.runtime"
    "$PYTHON_BIN" - "$PROJECT_DIR" "$PLIST" "$PYTHON_BIN" "$MODE" <<'PY'
import plistlib, sys
from pathlib import Path
root, target, python, mode = sys.argv[1:]
config = {
 'Label':'com.ultron.adb-qa',
 'ProgramArguments':['/bin/zsh', root+'/scripts/run-service.sh', python, mode],
 'WorkingDirectory':root, 'RunAtLoad':True, 'KeepAlive':True,
 'ThrottleInterval':10,
 'EnvironmentVariables':{'PATH':str(Path(python).parent)+':/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'},
 'StandardOutPath':root+'/.runtime/service.log',
 'StandardErrorPath':root+'/.runtime/service-error.log'
}
with open(target,'wb') as stream: plistlib.dump(config,stream)
PY
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    print "已安裝登入啟動服務（$MODE）；http://127.0.0.1:8765"
    ;;
  start) launchctl bootstrap "$DOMAIN" "$PLIST" ;;
  stop) launchctl bootout "$DOMAIN/$LABEL" ;;
  restart) launchctl kickstart -k "$DOMAIN/$LABEL" ;;
  status) launchctl print "$DOMAIN/$LABEL" ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    if [[ -f "$PLIST" ]]; then mv "$PLIST" "$PLIST.disabled"; fi
    print '已停用登入啟動；資料庫保留。'
    ;;
  *) print -u2 '使用：scripts/service.sh {install [mock|real]|start|stop|restart|status|uninstall}'; exit 1 ;;
esac
