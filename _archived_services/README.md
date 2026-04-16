# שירותים מוקפאים

שירותים שהיו פעילים ובוטלו. שמורים כאן לשחזור עתידי.

---

## Hermes Gateway

**מה זה:** סוכן AI (Hermes) עם חיבור לטלגרם ו-WhatsApp.

**מצב:** מוקפא מ-11 באפריל 2026.

**קוד:** `~/.hermes/hermes-agent/`
**קונפיגורציה:** `~/.hermes/config.yaml`
**לוגים:** `~/.hermes/logs/`
**LaunchAgent:** `launchagents/ai.hermes.gateway.plist`

### איך להחיות

```bash
# 1. העתק את ה-LaunchAgent למקומו
cp ~/Desktop/workspace/_archived_services/launchagents/ai.hermes.gateway.plist ~/Library/LaunchAgents/

# 2. טען אותו
launchctl load ~/Library/LaunchAgents/ai.hermes.gateway.plist

# 3. בדוק מצב
hermes gateway status
```

---

## OpenClaw Gateway

**מה זה:** סוכן AI (OpenClaw) עם חיבור לטלגרם.

**מצב:** מוקפא מ-11 באפריל 2026.

**קוד:** npm package — `/opt/homebrew/lib/node_modules/openclaw/`
**נתונים:** `openclaw-data/` (בתיקייה זו)
**LaunchAgent:** `launchagents/ai.openclaw.gateway.plist`

### איך להחיות

```bash
# 1. שחזר את הנתונים
cp -r ~/Desktop/workspace/_archived_services/openclaw-data/ ~/.openclaw/

# 2. העתק את ה-LaunchAgent למקומו
cp ~/Desktop/workspace/_archived_services/launchagents/ai.openclaw.gateway.plist ~/Library/LaunchAgents/

# 3. טען אותו
launchctl load ~/Library/LaunchAgents/ai.openclaw.gateway.plist
```

---

**שים לב:** הטוקנים של טלגרם ומפתחות ה-API שמורים בתוך קבצי ה-plist.
