#!/bin/bash
# ════════════════════════════════════════
#  העלה תמונות לאתר אנדרוס
#  גרור תמונות מעובדות לתיקיית מוכן-לאתר
#  ואז לחץ פעמיים על הקובץ הזה
# ════════════════════════════════════════

READY_DIR="/Users/itairaziel/Desktop/workspace/Andros2/מוכן-לאתר"
WEBSITE_IMAGES="/Users/itairaziel/Desktop/workspace/andros-house/images"
WEBSITE_DIR="/Users/itairaziel/Desktop/workspace/andros-house"

# ── בדוק שיש תמונות ──────────────────
shopt -s nullglob
files=("$READY_DIR"/*.{jpg,jpeg,JPG,JPEG,png,PNG})
count=${#files[@]}

if [ "$count" -eq 0 ]; then
  osascript -e 'display alert "אין תמונות" message "תיקיית מוכן-לאתר ריקה. ייצא תמונות לשם מתוך Photos ונסה שוב." as warning'
  exit 1
fi

osascript -e "display notification \"מעבד $count תמונות...\" with title \"העלאה לאתר\""

# ── כווץ והעתק ───────────────────────
for file in "${files[@]}"; do
  filename=$(basename "$file")
  dest="$WEBSITE_IMAGES/$filename"

  cp "$file" "$dest"

  # כווץ אם גדולה מ-1600px
  width=$(sips -g pixelWidth "$dest" | awk '/pixelWidth/{print $2}')
  if [ "$width" -gt 1600 ]; then
    sips -Z 1600 -s formatOptions 80 "$dest" > /dev/null 2>&1
  fi

  echo "✓ $filename"
done

# ── git commit & push ─────────────────
cd "$WEBSITE_DIR"
git add images/
git commit -m "Update images: $count photos from Photos editing session"
git push

if [ $? -eq 0 ]; then
  # ── נקה את תיקיית הביניים ──────────
  rm "${files[@]}"

  osascript -e "display alert \"✅ הועלו $count תמונות לאתר\" message \"Vercel יעדכן תוך כדקה.\""
else
  osascript -e 'display alert "❌ שגיאה בהעלאה" message "git push נכשל. בדוק חיבור לאינטרנט." as warning'
fi
