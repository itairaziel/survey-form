"""Apply organizational changes to Google Drive."""

import re
from collections import defaultdict

from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn, MofNCompleteColumn
from rich.prompt import Confirm, Prompt

from scanner import DriveFile, ScanResult

console = Console()

# Mime types that are text/document — never auto-delete duplicates
TEXT_MIMES = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
    "application/vnd.google-apps.form",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
    "text/plain",
    "text/csv",
    "application/pdf",
    "application/json",
    "text/html",
}

# Mime types that are video — auto-delete smaller copies
VIDEO_MIMES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm",
    "video/mpeg",
}


def _is_text(f: DriveFile) -> bool:
    return f.mime_type in TEXT_MIMES


def _is_video(f: DriveFile) -> bool:
    return f.mime_type in VIDEO_MIMES


# Camera/device filename prefixes → folder label
_CAMERA_PREFIXES = [
    ("DJI", "DJI"),
    ("GOPR", "GoPro"),
    ("GP", "GoPro"),
    ("GH", "GoPro"),
    ("MVI_", "Camera"),
    ("MTS", "Camera"),
    ("VID_", "Phone"),
    ("IMG_", "Phone"),
]


def _detect_video_group(f: DriveFile, folder_map: dict) -> str:
    """Return a meaningful group name for a video file."""
    # If the file is inside a named folder, use that folder's name
    if f.parents:
        parent = folder_map.get(f.parents[0])
        if parent:
            return parent.name

    # File is at root — detect from filename
    name_upper = f.name.upper()
    for prefix, label in _CAMERA_PREFIXES:
        if name_upper.startswith(prefix):
            m = re.search(r"(\d{4})[-_]?(\d{2})", f.name)
            if m:
                y, mo = m.group(1), m.group(2)
                if 2000 <= int(y) <= 2030:
                    return f"{label} {y}-{mo}"
            return label

    # Date pattern in filename
    m = re.search(r"(\d{4})[-_](\d{2})[-_]?\d{2}", f.name)
    if m:
        y, mo = m.group(1), m.group(2)
        if 2000 <= int(y) <= 2030:
            return f"Video {y}-{mo}"

    # Fall back to modified year-month
    if f.modified and len(f.modified) >= 7:
        return f"Video {f.modified[:7]}"

    return "Video - Uncategorized"


# ── Folder creation ────────────────────────────────────────────────────────────

def _ensure_folder(service, name: str, parent_id: str, dry_run: bool) -> str:
    """Return existing or create a new folder. Returns the folder ID."""
    query = (
        f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder'"
        f" and '{parent_id}' in parents and trashed = false"
    )
    res = service.files().list(q=query, fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    if dry_run:
        console.print(f"  [dim][dry-run] Would create folder: {name}[/dim]")
        return f"dry-run-{name}"

    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


# ── Move files to categorized folders ─────────────────────────────────────────

def organize_root_files(service, scan: ScanResult, dry_run: bool = True):
    """Move root-level files into category folders."""
    if not scan.root_files:
        console.print("[green]אין קבצים פזורים ב-root[/green]")
        return

    console.print(f"\n[bold]קבצים פזורים ב-root:[/bold] {len(scan.root_files)}")

    by_category: dict[str, list[DriveFile]] = {}
    for f in scan.root_files:
        by_category.setdefault(f.category, []).append(f)

    for category, files in sorted(by_category.items()):
        console.print(f"\n  [cyan]{category}[/cyan] ({len(files)} קבצים):")
        for f in files[:5]:
            console.print(f"    • {f.name}")
        if len(files) > 5:
            console.print(f"    ... ועוד {len(files) - 5}")

    if dry_run:
        console.print("\n[yellow][dry-run] לא בוצעו שינויים[/yellow]")
        return

    if not Confirm.ask("\nלהעביר את הקבצים לתיקיות לפי קטגוריה?"):
        return

    root_id = service.files().get(fileId="root", fields="id").execute()["id"]

    total = len(scan.root_files)
    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("מעביר קבצים...", total=total)
        for category, files in by_category.items():
            folder_id = _ensure_folder(service, category, root_id, dry_run)
            for f in files:
                service.files().update(
                    fileId=f.id,
                    addParents=folder_id,
                    removeParents=root_id,
                    fields="id, parents",
                ).execute()
                progress.advance(task)

    console.print(f"\n[bold green]הועברו {total} קבצים לתיקיות[/bold green]")


# ── Duplicates ─────────────────────────────────────────────────────────────────

def _pick_keeper(files: list[DriveFile]) -> DriveFile:
    """Choose which file to keep: for videos pick largest, otherwise newest."""
    if files and _is_video(files[0]):
        return max(files, key=lambda f: f.size or 0)
    return max(files, key=lambda f: f.modified or "")


def handle_duplicates(service, scan: ScanResult, dry_run: bool = True):
    """
    Duplicate handling rules:
    - Text/document files → skip (never auto-delete)
    - Video files → auto-trash all but the largest
    - Other files → ask per group
    """
    if not scan.duplicates:
        console.print("[green]לא נמצאו כפילויות[/green]")
        return

    # Split into buckets
    text_groups: dict[str, list[DriveFile]] = {}
    video_groups: dict[str, list[DriveFile]] = {}
    other_groups: dict[str, list[DriveFile]] = {}

    for name, files in scan.duplicates.items():
        if _is_text(files[0]):
            text_groups[name] = files
        elif _is_video(files[0]):
            video_groups[name] = files
        else:
            other_groups[name] = files

    console.print(f"\n[bold]קבוצות כפילויות:[/bold] {scan.duplicate_groups} ({scan.duplicate_files} קבצים עודפים)")
    console.print(f"  [dim]טקסט/מסמכים (מדולג): {len(text_groups)}[/dim]")
    console.print(f"  [cyan]וידאו (שומר גדול ביותר): {len(video_groups)}[/cyan]")
    console.print(f"  [yellow]אחר (ישאל): {len(other_groups)}[/yellow]")

    trashed = 0
    skipped_text = 0

    # ── Text: always skip ──────────────────────────────────────────────────────
    skipped_text = len(text_groups)
    if skipped_text:
        console.print(f"\n[dim]דולג על {skipped_text} קבוצות מסמכים (לא נמחקות)[/dim]")

    # ── Video: export report only, never auto-delete ──────────────────────────
    if video_groups:
        report_path = "video_duplicates.txt"
        lines = ["כפילויות וידאו — בדוק ידנית לפני מחיקה\n", "=" * 60 + "\n\n"]
        total_video_extras = 0
        for name, files in video_groups.items():
            keeper = _pick_keeper(files)
            to_delete = [f for f in files if f.id != keeper.id]
            total_video_extras += len(to_delete)
            lines.append(f"שם: {keeper.name}\n")
            for f in files:
                tag = ">>> ישמר" if f.id == keeper.id else "    יימחק"
                size_mb = f"{f.size // (1024*1024)} MB" if f.size else "?"
                drive_url = f"https://drive.google.com/file/d/{f.id}/view"
                lines.append(f"  {tag}  [{size_mb}]  {drive_url}\n")
            lines.append("\n")

        with open(report_path, "w", encoding="utf-8") as fp:
            fp.writelines(lines)

        console.print(f"\n[bold cyan]וידאו — {len(video_groups)} קבוצות, {total_video_extras} עודפים[/bold cyan]")
        console.print(f"  נשמר דוח ב: [bold]{report_path}[/bold]")
        console.print("  [dim]פתח את הקישורים בדרייב, בדוק ידנית, ואז מחק מה שתרצה[/dim]")

    # ── Other: ask per group (capped at 30) ───────────────────────────────────
    if other_groups:
        console.print(f"\n[bold yellow]קבצים אחרים — בחר לכל קבוצה:[/bold yellow]")
        shown = 0
        for name, files in other_groups.items():
            if shown >= 30:
                console.print(f"  [dim]... ועוד {len(other_groups) - shown} קבוצות[/dim]")
                break
            keeper = _pick_keeper(files)
            to_delete = [f for f in files if f.id != keeper.id]
            console.print(f"\n  [yellow]⚠[/yellow] [bold]{keeper.name}[/bold] ({len(files)} עותקים)")
            for f in files:
                tag = "[green](ישאר)[/green]" if f.id == keeper.id else "[red](יימחק)[/red]"
                size_kb = f"{f.size // 1024} KB" if f.size else "?"
                modified = f.modified[:10] if f.modified else "?"
                console.print(f"    {tag} [{modified}] [{size_kb}]")

            shown += 1
            if dry_run:
                continue

            action = Prompt.ask("  מה לעשות?", choices=["trash", "skip", "quit"], default="skip")
            if action == "quit":
                break
            if action == "trash":
                for f in to_delete:
                    service.files().update(fileId=f.id, body={"trashed": True}).execute()
                    trashed += 1

    if not dry_run and trashed:
        console.print(f"\n[bold green]סה\"כ הועברו לפח: {trashed} קבצים[/bold green]")
    elif dry_run:
        console.print("\n[yellow][dry-run] לא בוצעו שינויים[/yellow]")


# ── Deep folders ───────────────────────────────────────────────────────────────

def report_deep_folders(scan: ScanResult):
    """Report on overly deep folder structures."""
    if not scan.deep_folders:
        console.print("[green]אין תיקיות עמוקות מדי[/green]")
        return

    console.print(f"\n[bold]תיקיות עמוקות מדי (עומק >= {scan.depth_threshold}):[/bold] {len(scan.deep_folders)}")
    for folder in sorted(scan.deep_folders, key=lambda f: -f.depth)[:20]:
        bar = "  " * min(folder.depth, 8) + "F"
        console.print(f"  depth={folder.depth}  {bar} {folder.name}")

    console.print("\n[dim]טיפ: שקול לאחד תיקיות ולהשטיח את המבנה ידנית[/dim]")


# ── Remove shared items ────────────────────────────────────────────────────────

def remove_shared_items(service, shared_files: list, dry_run: bool = True):
    """Remove shared-with-me items from the user's Drive view."""
    if not shared_files:
        console.print("[green]אין פריטים משותפים[/green]")
        return

    folders = [f for f in shared_files if f.is_folder]
    files = [f for f in shared_files if not f.is_folder]

    console.print(f"\n[bold]פריטים ששיתפו איתך:[/bold] {len(shared_files)}")
    console.print(f"  תיקיות: {len(folders)}  |  קבצים: {len(files)}")
    console.print("[dim]הסרה לא מוחקת את הפריטים — הם ימשיכו להתקיים אצל הבעלים[/dim]\n")

    # Show first 20
    for f in shared_files[:20]:
        icon = "F" if f.is_folder else "•"
        size = f"{f.size // (1024*1024)} MB" if f.size else ""
        console.print(f"  {icon} {f.name}  [dim]{size}[/dim]")
    if len(shared_files) > 20:
        console.print(f"  ... ועוד {len(shared_files) - 20}")

    if dry_run:
        console.print("\n[yellow][dry-run] לא בוצעו שינויים[/yellow]")
        return

    if not Confirm.ask(f"\nלהסיר {len(shared_files)} פריטים משותפים מהתצוגה שלך?"):
        return

    # Get the user's own email to find the right permission to delete
    about = service.about().get(fields="user").execute()
    user_email = about["user"]["emailAddress"].lower()

    removed = 0
    errors = 0
    skipped = 0
    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("מסיר פריטים משותפים...", total=len(shared_files))
        for f in shared_files:
            try:
                # Find our own permission on this file
                perms = service.permissions().list(
                    fileId=f.id,
                    fields="permissions(id,emailAddress)",
                ).execute()
                my_perm = next(
                    (p for p in perms.get("permissions", [])
                     if p.get("emailAddress", "").lower() == user_email),
                    None,
                )
                if my_perm:
                    service.permissions().delete(
                        fileId=f.id, permissionId=my_perm["id"]
                    ).execute()
                    removed += 1
                else:
                    # Inherited access (inside a shared folder) — can't remove individually
                    skipped += 1
            except Exception:
                errors += 1
            progress.advance(task)

    console.print(f"\n[bold green]הוסרו {removed} פריטים[/bold green]")
    if skipped:
        console.print(f"[dim]{skipped} פריטים הם חלק מתיקייה משותפת — לא ניתן להסיר אותם בנפרד[/dim]")
    if errors:
        console.print(f"[yellow]{errors} שגיאות[/yellow]")


# ── Consolidate videos ──────────────────────────────────────────────────────

def consolidate_videos(service, scan: ScanResult, dry_run: bool = True):
    """Move all owned video files into Videos/<GroupName> folders."""
    videos = [f for f in scan.all_files if _is_video(f)]

    if not videos:
        console.print("[green]אין קבצי וידאו[/green]")
        return

    # Group by detected label
    groups: dict[str, list[DriveFile]] = defaultdict(list)
    for f in videos:
        group = _detect_video_group(f, scan.folder_map)
        groups[group].append(f)

    sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
    total_gb = sum(f.size or 0 for f in videos) / (1024 ** 3)

    console.print(f"\n[bold]קבצי וידאו:[/bold] {len(videos)} ({total_gb:.1f} GB)")
    console.print(f"[bold]קבוצות שייווצרו ב-Videos/:[/bold] {len(groups)}\n")

    for name, files in sorted_groups[:30]:
        size_mb = sum(f.size or 0 for f in files) // (1024 * 1024)
        console.print(f"  [cyan]{name}[/cyan] — {len(files)} קבצים ({size_mb} MB)")
    if len(sorted_groups) > 30:
        console.print(f"  ... ועוד {len(sorted_groups) - 30} קבוצות")

    if dry_run:
        console.print("\n[yellow][dry-run] לא בוצעו שינויים[/yellow]")
        console.print("[dim]להפעיל שינויים: python main.py consolidate-videos --no-dry-run[/dim]")
        return

    if not Confirm.ask(f"\nליצור Videos/ ולהעביר {len(videos)} קבצים?"):
        return

    root_id = service.files().get(fileId="root", fields="id").execute()["id"]
    videos_root_id = _ensure_folder(service, "Videos", root_id, dry_run=False)

    folder_cache: dict[str, str] = {}
    moved = 0
    errors = 0

    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("מאחד קבצי וידאו...", total=len(videos))
        for group_name, files in sorted_groups:
            if group_name not in folder_cache:
                folder_cache[group_name] = _ensure_folder(
                    service, group_name, videos_root_id, dry_run=False
                )
            dest_id = folder_cache[group_name]
            for f in files:
                try:
                    service.files().update(
                        fileId=f.id,
                        addParents=dest_id,
                        removeParents=",".join(f.parents) if f.parents else "",
                        fields="id, parents",
                    ).execute()
                    moved += 1
                except Exception:
                    errors += 1
                progress.advance(task)

    console.print(f"\n[bold green]הועברו {moved} קבצי וידאו לתיקיית Videos/[/bold green]")
    if errors:
        console.print(f"[yellow]{errors} שגיאות[/yellow]")
    console.print("\n[dim]נכנס לגוגל דרייב → תיקיית 'Videos' → מחק תיקיות שלמות[/dim]")


# ── Empty folders ────────────────────────────────────────────────────────────

def handle_empty_folders(service, scan: ScanResult, dry_run: bool = True):
    """Find owned folders with no owned children and offer to trash them."""
    parent_ids: set[str] = set()
    for f in scan.all_files:
        for pid in f.parents:
            parent_ids.add(pid)

    candidates = [f for f in scan.all_files if f.is_folder and f.id not in parent_ids]

    if not candidates:
        console.print("[green]אין תיקיות ריקות[/green]")
        return

    console.print(f"\n[bold]תיקיות ריקות (ללא קבצים שלך):[/bold] {len(candidates)}")
    console.print("[dim]בודק שאין בהן קבצים של אחרים לפני מחיקה...[/dim]\n")

    for f in candidates[:20]:
        console.print(f"  F {f.name}")
    if len(candidates) > 20:
        console.print(f"  ... ועוד {len(candidates) - 20}")

    if dry_run:
        console.print("\n[yellow][dry-run] לא בוצעו שינויים[/yellow]")
        return

    if not Confirm.ask(f"\nלהעביר {len(candidates)} תיקיות ריקות לפח?"):
        return

    trashed = skipped = errors = 0

    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("מעביר תיקיות ריקות לפח...", total=len(candidates))
        for f in candidates:
            try:
                res = service.files().list(
                    q=f"'{f.id}' in parents and trashed=false",
                    fields="files(id)",
                    pageSize=1,
                ).execute()
                if res.get("files"):
                    skipped += 1
                else:
                    service.files().update(fileId=f.id, body={"trashed": True}).execute()
                    trashed += 1
            except Exception:
                errors += 1
            progress.advance(task)

    console.print(f"\n[bold green]הועברו לפח: {trashed} תיקיות[/bold green]")
    if skipped:
        console.print(f"[dim]{skipped} תיקיות דולגו — יש בהן קבצים של אחרים[/dim]")
    if errors:
        console.print(f"[yellow]{errors} שגיאות[/yellow]")


# ── Mixed folders (owned folder + foreign files) ─────────────────────────────

def report_mixed_folders(scan: ScanResult, foreign_files: list[dict]):
    """Report owned folders that contain files belonging to other users."""
    owned_folder_ids = set(scan.folder_map.keys())

    by_folder: dict[str, list[dict]] = defaultdict(list)
    for item in foreign_files:
        for pid in item.get("parents", []):
            if pid in owned_folder_ids:
                by_folder[pid].append(item)
                break

    if not by_folder:
        console.print("[green]אין תיקיות שלך שמכילות קבצים של אחרים[/green]")
        return

    sorted_folders = sorted(by_folder.items(), key=lambda x: -len(x[1]))
    console.print(f"\n[bold]תיקיות שלך עם קבצים של אחרים:[/bold] {len(by_folder)}")
    console.print("[dim]אלו הן הסיבה שלא ניתן למחוק — יש בהן תוכן של אחרים[/dim]\n")

    for folder_id, items in sorted_folders[:20]:
        folder = scan.folder_map[folder_id]
        console.print(f"  [yellow]{folder.name}[/yellow] — {len(items)} קבצים של אחרים")
        for item in items[:3]:
            owner = (item.get("owners") or [{}])[0].get("displayName", "?")
            console.print(f"    • {item['name']}  [dim](בעלים: {owner})[/dim]")
        if len(items) > 3:
            console.print(f"    ... ועוד {len(items) - 3}")

    if len(sorted_folders) > 20:
        console.print(f"\n  ... ועוד {len(sorted_folders) - 20} תיקיות")

    console.print("\n[dim]פתרון: בקש מהבעלים להסיר את השיתוף, ואז תוכל למחוק[/dim]")
