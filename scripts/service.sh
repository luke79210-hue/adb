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
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    "$PYTHON_BIN" "$PROJECT_DIR/scripts/install_service.py" "$PROJECT_DIR" "$HOME/Library/Application Support/Ultron ADB QA" "$PYTHON_BIN" "$MODE" "$PLIST"
    launchctl bootstrap "$DOMAIN" "$PLIST"
    launchctl kickstart "$DOMAIN/$LABEL"
    print "已安裝並要求啟動服務（$MODE）；http://127.0.0.1:8765"
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
