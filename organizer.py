"""桌面文件按规则移动到归档目录（简洁版，无网络、无壁纸）。"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FALLBACK_FOLDER = "其它"


def default_config_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    dir_path = Path(base) / "DesktopTidy"
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path / "config.json"


def load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_config(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def undo_log_path(config_path: Path) -> Path:
    return config_path.parent / "undo_stack.jsonl"


@dataclass(frozen=True)
class MoveRecord:
    src: str
    dst: str

    def to_json(self) -> dict[str, str]:
        return {"src": self.src, "dst": self.dst}

    @staticmethod
    def from_json(obj: dict[str, str]) -> MoveRecord:
        return MoveRecord(src=obj["src"], dst=obj["dst"])


@dataclass(frozen=True)
class MovePlan:
    src: str
    dst: str


def desktop_dir(cfg: dict | None = None) -> Path:
    """尽量兼容英文桌面、中文桌面、OneDrive 桌面；可通过 config 的 desktop 字段覆盖。"""
    if cfg:
        custom = (cfg.get("desktop") or "").strip()
        if custom:
            p = Path(custom).expanduser()
            return p.resolve()
    user = Path.home()
    candidates = [
        user / "Desktop",
        user / "桌面",
        user / "OneDrive" / "Desktop",
        user / "OneDriveDesktop",
    ]
    for p in candidates:
        if p.is_dir():
            return p.resolve()
    return (user / "Desktop").resolve()


def resolve_archive_root(cfg: dict[str, Any]) -> Path:
    raw = (cfg.get("archive_root") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "Documents" / "桌面整理").resolve()


def ensure_extension_key(ext: str) -> str:
    e = ext.strip().lower()
    if not e:
        return ""
    if not e.startswith("."):
        e = "." + e
    return e


def safe_subfolder_name(folder: str) -> str:
    """Return a single safe archive child folder name."""
    cleaned = (folder or "").strip()
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    cleaned = cleaned.replace(":", "_")
    if cleaned in {"", ".", ".."}:
        return FALLBACK_FOLDER
    while ".." in cleaned:
        cleaned = cleaned.replace("..", "_")
    return cleaned.strip(" .") or FALLBACK_FOLDER


def unique_destination(dest_dir: Path, filename: str) -> Path:
    dest = dest_dir / filename
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    while True:
        candidate = dest_dir / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"
        if not candidate.exists():
            return candidate


def normalize_rules(rules: dict[str, str]) -> dict[str, str]:
    norm_rules: dict[str, str] = {}
    for ext, folder in rules.items():
        key = ensure_extension_key(ext)
        if not key:
            continue
        norm_rules[key] = safe_subfolder_name(str(folder))
    return norm_rules


def plan_organize(
    *,
    desktop: Path,
    archive_root: Path,
    rules: dict[str, str],
    skip_dirs: bool = True,
) -> tuple[list[MovePlan], list[str]]:
    logs: list[str] = []
    plans: list[MovePlan] = []
    norm_rules = normalize_rules(rules)

    if not desktop.is_dir():
        return [], [f"桌面路径不存在或不可访问: {desktop}"]

    for entry in sorted(desktop.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_dir() and skip_dirs:
            continue
        if not entry.is_file():
            continue
        suffix = entry.suffix.lower()
        if suffix not in norm_rules:
            continue
        dest_dir = archive_root / norm_rules[suffix]
        dest = unique_destination(dest_dir, entry.name)
        plans.append(MovePlan(src=str(entry), dst=str(dest)))
        logs.append(f"将移动: {entry.name} → {dest}")

    if not logs:
        logs.append("没有匹配规则的文件需要移动（未改动桌面）。")
    return plans, logs


def move_one_file(src: Path, archive_root: Path, subfolder: str, *, label: str = "移动") -> tuple[MoveRecord | None, str]:
    if not src.is_file():
        return None, f"跳过（非文件）: {src}"

    safe_folder = safe_subfolder_name(subfolder)
    dest_dir = archive_root / safe_folder
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = unique_destination(dest_dir, src.name)
        shutil.move(str(src), str(dest))
    except OSError as e:
        return None, f"{label}失败: {src} → {dest_dir}，原因: {e}"

    return MoveRecord(src=str(src), dst=str(dest)), f"{label}: {src.name} → {dest}"


def organize_batch(
    *,
    desktop: Path,
    archive_root: Path,
    rules: dict[str, str],
    skip_dirs: bool = True,
) -> tuple[list[MoveRecord], list[str]]:
    """
    将桌面上匹配 rules 后缀的文件移动到 archive_root/<文件夹>/。
    返回 (移动记录, 日志行)。
    """
    logs: list[str] = []
    records: list[MoveRecord] = []

    norm_rules = normalize_rules(rules)

    if not desktop.is_dir():
        return [], [f"桌面路径不存在或不可访问: {desktop}"]

    for entry in sorted(desktop.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_dir():
            if skip_dirs:
                continue
        if not entry.is_file():
            continue
        suffix = entry.suffix.lower()
        if suffix not in norm_rules:
            continue
        record, line = move_one_file(entry, archive_root, norm_rules[suffix])
        logs.append(line)
        if record:
            records.append(record)

    if not logs:
        logs.append("没有匹配规则的文件需要移动（未改动桌面）。")
    return records, logs


def move_paths_to_folder(
    paths: list[Path],
    archive_root: Path,
    subfolder: str,
) -> tuple[list[MoveRecord], list[str]]:
    """
    将给定文件路径移动到 archive_root/<subfolder>/。
    用于需要主动归档指定文件的场景；逻辑与 organize_batch 中移动文件一致。
    """
    logs: list[str] = []
    records: list[MoveRecord] = []
    if not paths:
        return [], ["未接收到任何文件。"]

    for raw in paths:
        src = Path(raw).resolve()
        record, line = move_one_file(src, archive_root, subfolder, label="[分区]")
        logs.append(line)
        if record:
            records.append(record)

    if not records and not logs:
        logs.append("没有有效文件。")
    return records, logs


def append_undo_batch(undo_path: Path, batch_id: str, records: list[MoveRecord]) -> None:
    payload = {
        "id": batch_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "moves": [r.to_json() for r in records],
    }
    undo_path.parent.mkdir(parents=True, exist_ok=True)
    with undo_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def pop_last_undo_batch(undo_path: Path) -> dict[str, Any] | None:
    if not undo_path.is_file():
        return None
    lines = undo_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return None
    last = json.loads(lines[-1])
    new_content = "\n".join(lines[:-1])
    if new_content:
        undo_path.write_text(new_content + "\n", encoding="utf-8")
    else:
        undo_path.unlink()
    return last


def _write_undo_batches(undo_path: Path, batches: list[dict[str, Any]]) -> None:
    if not batches:
        if undo_path.is_file():
            undo_path.unlink()
        return
    undo_path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(batch, ensure_ascii=False) for batch in batches)
    undo_path.write_text(content + "\n", encoding="utf-8")


def undo_last_batch(undo_path: Path) -> tuple[bool, list[str]]:
    """把最近一次整理反向移动回去。"""
    if not undo_path.is_file():
        batch = None
        lines: list[str] = []
    else:
        lines = undo_path.read_text(encoding="utf-8").splitlines()
        batch = json.loads(lines[-1]) if lines else None
    logs: list[str] = []
    if not batch:
        logs.append("没有可撤销的操作。")
        return False, logs

    remaining_moves: list[dict[str, str]] = []
    moves = batch.get("moves") or []
    for m in reversed(moves):
        src = Path(m["dst"])
        dst = Path(m["src"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not src.is_file():
            logs.append(f"跳过（源不存在）: {src}")
            continue
        if dst.exists():
            logs.append(f"冲突，跳过: {dst}")
            remaining_moves.append(m)
            continue
        try:
            shutil.move(str(src), str(dst))
            logs.append(f"撤销: {src.name} → {dst}")
        except OSError as e:
            logs.append(f"撤销失败: {src} → {dst}，原因: {e}")
            remaining_moves.append(m)

    batches = [json.loads(line) for line in lines[:-1]]
    if remaining_moves:
        retry_batch = dict(batch)
        retry_batch["moves"] = list(reversed(remaining_moves))
        batches.append(retry_batch)
        logs.append("部分文件未撤销，已保留撤销记录，处理冲突后可再次撤销。")
        _write_undo_batches(undo_path, batches)
        return False, logs

    _write_undo_batches(undo_path, batches)
    return True, logs
