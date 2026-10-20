"""把微信合并转发的 ZIP 写成 Obsidian 库里的一篇 Markdown 笔记。

ZIP 结构（微信 4.1.13 实测，2026-10-04）：
    聊天记录.txt
    聊天记录内的图片、视频和文件/<附件>
TXT 每条消息：「·发送者」行、「yyyy年M月d日 HH:mm」行、正文、空行。
正文里的附件写成「[图片] 文件名」。

Obsidian 的约定（1.14.4）：
    - 图片放 <目录>/i/，正文写 ![](i/名字)；其他附件放 <目录>/files/
    - 链接以「/」开头会被当成库根目录，所以写相对笔记的路径
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote

DEFAULT_ROOT = Path.home() / "xuxu_note/xuxu_n/wx"
TRANSCRIPT_NAME = "聊天记录.txt"

RECORD_HEADER = re.compile(r"(?m)^·([^\n]+)\n(\d{4}年\d{1,2}月\d{1,2}日 \d{2}:\d{2})\n")

IMAGE, VIDEO, OTHER = "image", "video", "other"
# 微信 4.1.13 的附件标记（简体、繁体、英文），整体匹配，所以「[视频号]」不算「[视频]」。
MARKERS = {
    f"[{name}]": kind
    for kind, names in (
        (IMAGE, ["图片", "圖片", "photo", "image"]),
        (VIDEO, ["视频", "小视频", "影片", "微影片", "video"]),
        (
            OTHER,
            [
                "文件",
                "檔案",
                "file",
                "语音",
                "語音",
                "录音",
                "錄音",
                "音频",
                "音訊",
                "voice",
                "audio",
                "recording",
                "表情",
                "动画表情",
                "動態貼圖",
                "sticker",
            ],
        ),
    )
    for name in names
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".heic"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".ogv"}


@dataclass
class Record:
    sender: str
    at: datetime
    text: str


def parse_records(body: str) -> list[Record]:
    """解析失败返回空列表，由调用方原样保留全文。"""
    body = body.replace("\r\n", "\n").lstrip("﻿")
    matches = list(RECORD_HEADER.finditer(body))
    if not matches or matches[0].start() != 0:
        return []
    records = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        try:
            # 微信 TXT 是本机本地时间、不带时区，按原样当本地时间用。
            at = datetime.strptime(match.group(2), "%Y年%m月%d日 %H:%M")  # noqa: DTZ007
        except ValueError:
            return []
        records.append(Record(match.group(1), at, body[match.end() : end].strip()))
    return records


def kind_of(name: str) -> str:
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return IMAGE
    if suffix in VIDEO_EXTENSIONS:
        return VIDEO
    return OTHER


def attachment_in(line: str, by_name: dict[str, list[str]]) -> tuple[str, str] | None:
    """一行正文如果只是在引用附件，返回 (ZIP 内路径, 种类)。同名有歧义时不认。"""
    text = line.strip()
    reference, marked = text, None
    if text.startswith("[") and "]" in text:
        close = text.index("]") + 1
        rest = text[close:].lstrip(" \t")
        kind = MARKERS.get(text[:close].lower())
        if kind and rest:
            reference, marked = rest, kind
    reference = reference.removeprefix("./")
    candidates = by_name.get(PurePosixPath(reference).name, [])
    if len(candidates) != 1:
        return None
    member = candidates[0]
    return member, marked or kind_of(member)


def escape(line: str) -> str:
    """聊天文字是数据：只转义会改变笔记结构的东西。"""
    text = (
        line.replace("\\", "\\\\")
        .replace("<", "\\<")
        .replace("[", "\\[")
        .replace("`", "\\`")
    )
    trimmed = text.lstrip(" \t")
    indent = len(text) - len(trimmed)
    if not trimmed:
        return text
    first, rest = trimmed[0], trimmed[1:]
    is_rule = (
        len(trimmed) >= 3
        and first in "-=*_"
        and all(c in (first, " ") for c in trimmed)
    )
    is_marker = first in "#>" or (first in "-+*" and (rest[:1] == " " or not rest))
    digits = len(trimmed) - len(trimmed.lstrip("0123456789"))
    is_ordered = digits > 0 and trimmed[digits : digits + 1] in (".", ")")
    if is_ordered:
        text = text[: indent + digits] + "\\" + text[indent + digits :]
    elif is_rule or is_marker:
        text = text[:indent] + "\\" + text[indent:]
    # 行首四个空格会被当成代码块。
    return text.lstrip(" \t") if indent >= 4 else text


def sha256_of(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1 << 20), b""):
        digest.update(chunk)
    return digest.hexdigest()


def store_attachment(
    archive: zipfile.ZipFile, member: str, kind: str, root: Path
) -> str:
    """复制附件进笔记目录，返回笔记里用的链接。同名同内容复用，同名不同内容加序号。"""
    folder = "i" if kind == IMAGE else "files"
    target_dir = root / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    # 只取文件名：ZIP 内路径不可信，不能让它跳出目标目录。
    name = PurePosixPath(member).name
    stem, suffix = PurePosixPath(name).stem, PurePosixPath(name).suffix
    with archive.open(member) as source:
        wanted = sha256_of(source)
    serial = 1
    while True:
        candidate = target_dir / (name if serial == 1 else f"{stem}_{serial}{suffix}")
        if not candidate.exists():
            with archive.open(member) as source, candidate.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            break
        with candidate.open("rb") as existing:
            if sha256_of(existing) == wanted:
                break
        serial += 1
    return f"{folder}/{link_path(candidate.name)}"


def link_path(name: str) -> str:
    """中文原样保留；只编码会截断 Markdown 链接的字符，Obsidian 解析时会解码。"""
    return "".join(f"%{ord(c):02X}" if c in "% ()<>" else c for c in name)


def link(label: str, href: str, kind: str) -> str:
    label = label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return ("!" if kind == IMAGE else "") + f"[{label}]({href})"


def safe_name(text: str) -> str:
    # 「/」是路径分隔符；「:」在访达里显示成「/」。
    return re.sub(r"[/:\n\r\t]", "_", text).strip() or "微信聊天记录"


def title_for(records: list[Record], imported_at: datetime) -> str:
    if not records:
        return f"微信聊天记录 {imported_at:%Y-%m-%d %H%M%S}"
    counts = Counter(r.sender for r in records)
    senders = [name[:20] for name, _ in counts.most_common(2)]
    who = "、".join(senders) + (f"等{len(counts)}人" if len(counts) > 2 else "")
    start, end = min(r.at for r in records), max(r.at for r in records)
    if start.date() == end.date():
        span = f"{start:%Y-%m-%d %H%M}-{end:%H%M}"
    else:
        span = f"{start:%Y-%m-%d %H%M} 至 {end:%Y-%m-%d %H%M}"
    return f"{who} {span}"


def unique_note_path(root: Path, title: str) -> Path:
    base = safe_name(title)
    path, serial = root / f"{base}.md", 2
    while path.exists():
        path = root / f"{base} ({serial}).md"
        serial += 1
    return path


def render(
    records: list[Record], raw: str, attach, extras: list[str], imported_at: datetime
) -> str:
    """attach(line) -> 附件链接或 None；extras 是正文没引用到的附件链接。"""
    lines: list[str] = []
    if records:
        start, end = min(r.at for r in records), max(r.at for r in records)
        lines.append(
            f"> 微信聊天记录 · {len(records)} 条 · {start:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M}"
            f" · 导入于 {imported_at:%Y-%m-%d %H:%M}"
        )
        current_day = None
        for record in sorted(records, key=lambda r: r.at):
            day = f"{record.at:%Y-%m-%d}"
            if day != current_day:
                current_day = day
                lines += ["", f"## {day}"]
            lines += ["", f"**{escape(record.sender)}** {record.at:%H:%M}", ""]
            body = [attach(line) or escape(line) for line in record.text.split("\n")]
            # 行尾两个空格：消息自己的换行在预览里不被合并成一段。
            lines += [
                text + "  " if i + 1 < len(body) and text else text
                for i, text in enumerate(body)
            ]
    else:
        lines.append(
            f"> 微信聊天记录 · 没识别出时间格式，原文照录 · 导入于 {imported_at:%Y-%m-%d %H:%M}"
        )
        lines.append("")
        lines += ["    " + line for line in raw.replace("\r\n", "\n").split("\n")]
    if extras:
        lines += ["", "## 其他附件", ""] + [f"- {item}" for item in extras]
    return "\n".join(lines) + "\n"


def convert(zip_path: Path, root: Path, imported_at: datetime | None = None) -> Path:
    imported_at = imported_at or datetime.now()  # noqa: DTZ005 与聊天时间同为本地时间
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        members = [m for m in archive.namelist() if not m.endswith("/")]
        transcripts = [m for m in members if PurePosixPath(m).name == TRANSCRIPT_NAME]
        if not transcripts:
            transcripts = [m for m in members if m.lower().endswith(".txt")][:1]
        transcript = transcripts[0] if transcripts else None
        raw = archive.read(transcript).decode("utf-8", "replace") if transcript else ""
        records = parse_records(raw)

        files = [m for m in members if m != transcript]
        by_name: dict[str, list[str]] = {}
        for member in files:
            by_name.setdefault(PurePosixPath(member).name, []).append(member)

        stored: dict[str, str] = {}

        def href(member: str, kind: str) -> str:
            if member not in stored:
                stored[member] = store_attachment(archive, member, kind, root)
            return stored[member]

        def attach(line: str) -> str | None:
            found = attachment_in(line, by_name)
            if not found:
                return None
            member, kind = found
            return link(PurePosixPath(member).name, href(member, kind), kind)

        used = {
            found[0]
            for record in records
            for line in record.text.split("\n")
            if (found := attachment_in(line, by_name))
        }
        extras = [
            link(PurePosixPath(m).name, href(m, kind_of(m)), OTHER)
            for m in files
            if m not in used
        ]
        content = render(records, raw, attach, extras, imported_at)

    note = unique_note_path(root, title_for(records, imported_at))
    note.write_text(content, encoding="utf-8")
    return note


def notify(message: str) -> None:
    script = (
        f'display notification {applescript_string(message)} with title "存到 Obsidian"'
    )
    subprocess.run(["osascript", "-e", script], check=False)


def applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def open_in_obsidian(note: Path) -> None:
    uri = f"obsidian://open?path={quote(str(note), safe='')}"
    subprocess.run(["open", uri], check=False)


def main(argv: list[str]) -> int:
    root = Path(os.environ.get("WX2OB_ROOT", DEFAULT_ROOT))
    notes: list[Path] = []
    failures: list[str] = []
    for arg in argv:
        path = Path(arg)
        if not zipfile.is_zipfile(path):
            failures.append(f"不是 ZIP：{path.name}")
            continue
        try:
            note = convert(path, root)
        except Exception as error:  # noqa: BLE001 一个包坏了不影响同批其他包。
            failures.append(f"{path.name}：{error}")
            continue
        notes.append(note)
        print(f"  note: {note}")
    for failure in failures:
        print(f"  fail: {failure}", file=sys.stderr)

    if os.environ.get("WX2OB_QUIET"):
        return 1 if failures else 0
    if notes:
        notify(
            f"已存 {len(notes)} 篇到 Obsidian wx"
            + (f"，{len(failures)} 个失败" if failures else "")
        )
        open_in_obsidian(notes[-1])
    elif failures:
        notify("没存成：" + failures[0])
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
