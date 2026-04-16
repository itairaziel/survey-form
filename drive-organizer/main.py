#!/usr/bin/env python3
"""
drive-organizer — Google Drive cleanup tool
"""

import sys
import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from auth import get_drive_service
from scanner import scan, scan_shared, scan_foreign_in_owned
from organizer import (
    organize_root_files,
    handle_duplicates,
    report_deep_folders,
    remove_shared_items,
    consolidate_videos,
    handle_empty_folders,
    report_mixed_folders,
)

console = Console()


def print_summary(result):
    """Print a summary table of scan findings."""
    table = Table(title="סריקת Google Drive", show_header=True, header_style="bold cyan")
    table.add_column("ממצא", style="bold")
    table.add_column("כמות", justify="right")
    table.add_column("סטטוס")

    def status(count, good_label="תקין", bad_label="דורש טיפול"):
        return f"[green]{good_label}[/green]" if count == 0 else f"[yellow]{bad_label}[/yellow]"

    table.add_row("סה\"כ קבצים", str(result.total_files), "")
    table.add_row("סה\"כ תיקיות", str(result.total_folders), "")
    table.add_row(
        "קבצים פזורים ב-root",
        str(len(result.root_files)),
        status(len(result.root_files)),
    )
    table.add_row(
        "קבוצות כפילויות",
        str(result.duplicate_groups),
        status(result.duplicate_groups),
    )
    table.add_row(
        "קבצים כפולים עודפים",
        str(result.duplicate_files),
        status(result.duplicate_files),
    )
    table.add_row(
        f"תיקיות עמוקות (≥{result.depth_threshold})",
        str(len(result.deep_folders)),
        status(len(result.deep_folders)),
    )

    console.print(table)


@click.group()
def cli():
    """כלי לארגון Google Drive."""
    pass


@cli.command()
@click.option("--depth", default=4, help="סף עומק תיקיות (ברירת מחדל: 4)")
def scan_cmd(depth):
    """סרוק את הדרייב והצג דוח."""
    console.print(Panel("[bold blue]Google Drive Organizer[/bold blue]", expand=False))

    try:
        service = get_drive_service()
    except FileNotFoundError as e:
        console.print(f"[red]שגיאה:[/red] {e}")
        sys.exit(1)

    console.print("[dim]מתחבר...[/dim]")
    result = scan(service, depth_threshold=depth)

    print_summary(result)

    console.print("\n[bold]קבצים פזורים ב-root:[/bold]")
    if result.root_files:
        for f in result.root_files[:10]:
            console.print(f"  • {f.name}  [dim]({f.category})[/dim]")
        if len(result.root_files) > 10:
            console.print(f"  ... ועוד {len(result.root_files) - 10}")
    else:
        console.print("  [green]אין[/green]")

    console.print("\n[bold]כפילויות:[/bold]")
    if result.duplicates:
        for name, files in list(result.duplicates.items())[:5]:
            console.print(f"  • {files[0].name}  [dim]×{len(files)}[/dim]")
        if len(result.duplicates) > 5:
            console.print(f"  ... ועוד {len(result.duplicates) - 5} קבוצות")
    else:
        console.print("  [green]אין[/green]")

    console.print("\n[dim]הפעל [bold]organize[/bold] לטיפול בבעיות[/dim]")


@cli.command()
@click.option("--depth", default=4, help="סף עומק תיקיות")
@click.option("--dry-run/--no-dry-run", default=True, help="הדמיה בלבד (ברירת מחדל: כן)")
@click.option("--skip-root", is_flag=True, help="דלג על ארגון קבצי root")
@click.option("--skip-dupes", is_flag=True, help="דלג על כפילויות")
@click.option("--skip-deep", is_flag=True, help="דלג על תיקיות עמוקות")
def organize(depth, dry_run, skip_root, skip_dupes, skip_deep):
    """ארגן את הדרייב — העבר קבצים, נקה כפילויות."""
    console.print(Panel("[bold blue]Google Drive Organizer[/bold blue]", expand=False))

    if dry_run:
        console.print("[yellow]מצב dry-run — לא יבוצעו שינויים אמיתיים[/yellow]")
        console.print("[dim]להפעיל שינויים אמיתיים: --no-dry-run[/dim]\n")

    try:
        service = get_drive_service()
    except FileNotFoundError as e:
        console.print(f"[red]שגיאה:[/red] {e}")
        sys.exit(1)

    result = scan(service, depth_threshold=depth)
    print_summary(result)
    console.print()

    if not skip_root:
        console.rule("[bold]שלב 1: קבצים פזורים[/bold]")
        organize_root_files(service, result, dry_run=dry_run)

    if not skip_dupes:
        console.rule("[bold]שלב 2: כפילויות[/bold]")
        handle_duplicates(service, result, dry_run=dry_run)

    if not skip_deep:
        console.rule("[bold]שלב 3: תיקיות עמוקות[/bold]")
        report_deep_folders(result)

    console.print("\n[bold green]סיום![/bold green]")


@cli.command("remove-shared")
@click.option("--dry-run/--no-dry-run", default=True, help="הדמיה בלבד (ברירת מחדל: כן)")
def remove_shared_cmd(dry_run):
    """הסר פריטים ששיתפו איתך מהתצוגה שלך."""
    console.print(Panel("[bold blue]Google Drive Organizer — הסרת משותפים[/bold blue]", expand=False))

    if dry_run:
        console.print("[yellow]מצב dry-run — לא יבוצעו שינויים[/yellow]\n")

    try:
        service = get_drive_service()
    except FileNotFoundError as e:
        console.print(f"[red]שגיאה:[/red] {e}")
        sys.exit(1)

    shared = scan_shared(service)
    remove_shared_items(service, shared, dry_run=dry_run)


@cli.command("consolidate-videos")
@click.option("--depth", default=4, help="סף עומק תיקיות לסריקה")
@click.option("--dry-run/--no-dry-run", default=True, help="הדמיה בלבד (ברירת מחדל: כן)")
def consolidate_videos_cmd(depth, dry_run):
    """רכז את כל קבצי הוידאו לתיקיות לפי קבוצה."""
    console.print(Panel("[bold blue]Google Drive Organizer — ריכוז וידאו[/bold blue]", expand=False))

    if dry_run:
        console.print("[yellow]מצב dry-run — לא יבוצעו שינויים[/yellow]\n")

    try:
        service = get_drive_service()
    except FileNotFoundError as e:
        console.print(f"[red]שגיאה:[/red] {e}")
        sys.exit(1)

    result = scan(service, depth_threshold=depth)
    consolidate_videos(service, result, dry_run=dry_run)


@cli.command("empty-folders")
@click.option("--depth", default=4, help="סף עומק תיקיות לסריקה")
@click.option("--dry-run/--no-dry-run", default=True, help="הדמיה בלבד (ברירת מחדל: כן)")
def empty_folders_cmd(depth, dry_run):
    """מצא תיקיות ריקות והעבר לפח."""
    console.print(Panel("[bold blue]Google Drive Organizer — תיקיות ריקות[/bold blue]", expand=False))

    if dry_run:
        console.print("[yellow]מצב dry-run — לא יבוצעו שינויים[/yellow]\n")

    try:
        service = get_drive_service()
    except FileNotFoundError as e:
        console.print(f"[red]שגיאה:[/red] {e}")
        sys.exit(1)

    result = scan(service, depth_threshold=depth)
    handle_empty_folders(service, result, dry_run=dry_run)


@cli.command("find-mixed")
@click.option("--depth", default=4, help="סף עומק תיקיות לסריקה")
def find_mixed_cmd(depth):
    """מצא תיקיות שלך שמכילות קבצים של אחרים (סיבה לכך שלא ניתן למחוק)."""
    console.print(Panel("[bold blue]Google Drive Organizer — תיקיות מעורבות[/bold blue]", expand=False))

    try:
        service = get_drive_service()
    except FileNotFoundError as e:
        console.print(f"[red]שגיאה:[/red] {e}")
        sys.exit(1)

    result = scan(service, depth_threshold=depth)
    foreign = scan_foreign_in_owned(service, set(result.folder_map.keys()))
    report_mixed_folders(result, foreign)


# Allow running as: python main.py scan  OR  python main.py organize
cli.add_command(scan_cmd, name="scan")

if __name__ == "__main__":
    cli()
