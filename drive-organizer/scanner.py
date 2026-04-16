"""Scan and analyze Google Drive for organizational issues."""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

MIME_FOLDER = "application/vnd.google-apps.folder"

# Mime type → friendly category name
MIME_CATEGORIES = {
    "application/pdf": "PDFs",
    "image/jpeg": "Images",
    "image/png": "Images",
    "image/gif": "Images",
    "image/webp": "Images",
    "image/heic": "Images",
    "image/heif": "Images",
    "video/mp4": "Videos",
    "video/quicktime": "Videos",
    "video/x-msvideo": "Videos",
    "audio/mpeg": "Audio",
    "audio/wav": "Audio",
    "audio/x-m4a": "Audio",
    "application/zip": "Archives",
    "application/x-zip-compressed": "Archives",
    "application/x-rar-compressed": "Archives",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Documents",
    "application/msword": "Documents",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Spreadsheets",
    "application/vnd.ms-excel": "Spreadsheets",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "Presentations",
    "application/vnd.ms-powerpoint": "Presentations",
    "text/plain": "Text",
    "text/csv": "Spreadsheets",
    "application/json": "Code",
    "text/html": "Code",
    "application/vnd.google-apps.document": "Google Docs",
    "application/vnd.google-apps.spreadsheet": "Google Sheets",
    "application/vnd.google-apps.presentation": "Google Slides",
    "application/vnd.google-apps.form": "Google Forms",
}


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    parents: list[str]
    size: Optional[int]
    modified: str
    depth: int = 0

    @property
    def category(self) -> str:
        return MIME_CATEGORIES.get(self.mime_type, "Other")

    @property
    def is_folder(self) -> bool:
        return self.mime_type == MIME_FOLDER

    @property
    def in_root(self) -> bool:
        return not self.parents or self.parents == ["root"]


@dataclass
class ScanResult:
    all_files: list[DriveFile] = field(default_factory=list)
    root_files: list[DriveFile] = field(default_factory=list)
    duplicates: dict[str, list[DriveFile]] = field(default_factory=dict)
    deep_folders: list[DriveFile] = field(default_factory=list)
    folder_map: dict[str, DriveFile] = field(default_factory=dict)  # id → folder
    depth_threshold: int = 4

    @property
    def total_files(self) -> int:
        return len([f for f in self.all_files if not f.is_folder])

    @property
    def total_folders(self) -> int:
        return len([f for f in self.all_files if f.is_folder])

    @property
    def duplicate_groups(self) -> int:
        return len(self.duplicates)

    @property
    def duplicate_files(self) -> int:
        return sum(len(v) - 1 for v in self.duplicates.values())


def _fetch_all_items(service) -> list[dict]:
    """Fetch all files and folders from Drive (handles pagination)."""
    items = []
    page_token = None
    fields = "nextPageToken, files(id, name, mimeType, parents, size, modifiedTime, ownedByMe)"

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]סורק את הדרייב... {task.fields[count]} קבצים"),
        transient=True,
    ) as progress:
        task = progress.add_task("scan", total=None, count=0)
        while True:
            for attempt in range(3):
                try:
                    response = (
                        service.files()
                        .list(
                            pageSize=1000,
                            fields=fields,
                            pageToken=page_token,
                            includeItemsFromAllDrives=False,
                            supportsAllDrives=False,
                        )
                        .execute()
                    )
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    console.print(f"  [yellow]timeout, מנסה שוב... ({attempt + 2}/3)[/yellow]")
                    time.sleep(3)
            # Only keep files owned by the user
            owned = [f for f in response.get("files", []) if f.get("ownedByMe", False)]
            items.extend(owned)
            progress.update(task, count=len(items))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

    return items


def _build_depth_map(folder_map: dict[str, DriveFile]) -> dict[str, int]:
    """Calculate depth of every folder."""
    depth_cache: dict[str, int] = {}

    def get_depth(folder_id: str, visited: set) -> int:
        if folder_id in depth_cache:
            return depth_cache[folder_id]
        if folder_id in visited:
            return 0  # cycle guard
        visited.add(folder_id)

        folder = folder_map.get(folder_id)
        if not folder or not folder.parents:
            depth_cache[folder_id] = 0
            return 0

        parent_id = folder.parents[0]
        if parent_id not in folder_map:
            depth_cache[folder_id] = 0
            return 0

        depth = 1 + get_depth(parent_id, visited)
        depth_cache[folder_id] = depth
        return depth

    for fid in folder_map:
        get_depth(fid, set())

    return depth_cache


def scan(service, depth_threshold: int = 4) -> ScanResult:
    """Full Drive scan. Returns a ScanResult with all findings."""
    raw = _fetch_all_items(service)

    result = ScanResult(depth_threshold=depth_threshold)

    # Build DriveFile objects
    for item in raw:
        parents = item.get("parents", [])
        f = DriveFile(
            id=item["id"],
            name=item["name"],
            mime_type=item["mimeType"],
            parents=parents,
            size=int(item["size"]) if item.get("size") else None,
            modified=item.get("modifiedTime", ""),
        )
        result.all_files.append(f)
        if f.is_folder:
            result.folder_map[f.id] = f

    # Calculate depths
    depth_map = _build_depth_map(result.folder_map)
    for f in result.all_files:
        if f.parents:
            parent_id = f.parents[0]
            parent_depth = depth_map.get(parent_id, 0)
            f.depth = parent_depth + 1
        else:
            f.depth = 0

    # Root files (files not in any folder, or only in root)
    root_id = _get_root_id(service)
    for f in result.all_files:
        if f.is_folder:
            continue
        if not f.parents or f.parents[0] == root_id:
            result.root_files.append(f)

    # Duplicates (same name, not folder)
    name_groups: dict[str, list[DriveFile]] = defaultdict(list)
    for f in result.all_files:
        if not f.is_folder:
            name_groups[f.name.lower().strip()].append(f)
    result.duplicates = {k: v for k, v in name_groups.items() if len(v) > 1}

    # Deep folders
    for f in result.all_files:
        if f.is_folder:
            d = depth_map.get(f.id, 0)
            f.depth = d
            if d >= depth_threshold:
                result.deep_folders.append(f)

    return result


def _get_root_id(service) -> str:
    """Get the root folder ID."""
    root = service.files().get(fileId="root", fields="id").execute()
    return root["id"]


def scan_shared(service) -> list[DriveFile]:
    """Return all files/folders shared with the user that they don't own."""
    items = []
    page_token = None
    fields = "nextPageToken, files(id, name, mimeType, parents, size, modifiedTime, ownedByMe, sharingUser)"

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]סורק פריטים משותפים... {task.fields[count]}"),
        transient=True,
    ) as progress:
        task = progress.add_task("scan", total=None, count=0)
        while True:
            for attempt in range(3):
                try:
                    response = (
                        service.files()
                        .list(
                            q="sharedWithMe = true",
                            pageSize=1000,
                            fields=fields,
                            pageToken=page_token,
                        )
                        .execute()
                    )
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(3)
            for item in response.get("files", []):
                if not item.get("ownedByMe", True):
                    f = DriveFile(
                        id=item["id"],
                        name=item["name"],
                        mime_type=item["mimeType"],
                        parents=item.get("parents", []),
                        size=int(item["size"]) if item.get("size") else None,
                        modified=item.get("modifiedTime", ""),
                    )
                    items.append(f)
            progress.update(task, count=len(items))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

    return items


def scan_foreign_in_owned(service, owned_folder_ids: set) -> list[dict]:
    """Fetch files NOT owned by the user whose parent is an owned folder."""
    items = []
    page_token = None
    fields = "nextPageToken, files(id, name, mimeType, parents, owners)"

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]סורק קבצים של אחרים בתיקיות שלך... {task.fields[count]}"),
        transient=True,
    ) as progress:
        task = progress.add_task("scan", total=None, count=0)
        while True:
            for attempt in range(3):
                try:
                    response = (
                        service.files()
                        .list(
                            q="trashed=false",
                            pageSize=1000,
                            fields=fields,
                            pageToken=page_token,
                        )
                        .execute()
                    )
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(3)
            for item in response.get("files", []):
                # Skip files owned by the user
                if item.get("ownedByMe", True):
                    continue
                parents = item.get("parents", [])
                if any(pid in owned_folder_ids for pid in parents):
                    items.append(item)
            progress.update(task, count=len(items))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

    return items
