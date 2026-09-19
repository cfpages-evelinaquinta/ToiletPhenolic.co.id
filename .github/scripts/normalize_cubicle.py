#!/usr/bin/env python3
"""Idempotent cubicle URL flattening and stylesheet-path normalisation."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


NAME_RE = re.compile(r"^cubicle-[a-z0-9]+(?:-[a-z0-9]+)*$")
STYLESHEET_RE = re.compile(
    r"<link\b(?P<tag>[^>]*\brel\s*=\s*['\"][^'\"]*stylesheet[^'\"]*['\"][^>]*)>",
    re.IGNORECASE | re.DOTALL,
)
HREF_RE = re.compile(r"\bhref\s*=\s*([\"'])(?P<href>[^\"']+)\1", re.IGNORECASE)
WP_CONTENT_RE = re.compile(r"(\bhref\s*=\s*[\"'])\.\./wp-content/", re.IGNORECASE)


class TransformError(RuntimeError):
    pass


def read_text(path: Path) -> tuple[str, bytes]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    payload = raw[3:] if bom else raw
    try:
        return payload.decode("utf-8"), raw[:3] if bom else b""
    except UnicodeDecodeError as exc:
        raise TransformError(f"{path} is not UTF-8") from exc


def write_text(path: Path, text: str, bom: bytes) -> None:
    path.write_bytes(bom + text.encode("utf-8"))


def add_redirects(root: Path, names: list[str], changed: set[str]) -> None:
    if not names:
        return
    path = root / "_redirects"
    text, bom = read_text(path) if path.exists() else ("", b"")
    lines = text.splitlines()
    existing = set(lines)
    additions: list[str] = []
    for name in names:
        for line in (f"/{name}/ /{name}.html 301", f"/{name}/index.html /{name}.html 301"):
            if line not in existing:
                additions.append(line)
                existing.add(line)
    lines = additions + lines
    new_text = "\n".join(lines)
    if lines:
        new_text += "\n"
    if new_text != text:
        write_text(path, new_text, bom)
        changed.add("_redirects")


def flatten(root: Path) -> tuple[list[str], dict[str, int]]:
    changed: set[str] = set()
    moved = 0
    redirect_names: list[str] = []
    for source_dir in sorted(root.iterdir(), key=lambda item: item.name):
        if not source_dir.is_dir() or source_dir.is_symlink() or not NAME_RE.fullmatch(source_dir.name):
            continue
        source = source_dir / "index.html"
        if not source.exists():
            continue
        entries = list(source_dir.iterdir())
        if len(entries) != 1 or entries[0].name != "index.html":
            raise TransformError(f"source directory contains unexpected files: {source_dir.name}")
        if source.is_symlink() or not source.is_file():
            raise TransformError(f"source is not a regular file: {source.relative_to(root)}")
        destination = root / f"{source_dir.name}.html"
        source_bytes = source.read_bytes()
        if destination.exists():
            if destination.is_symlink() or not destination.is_file():
                raise TransformError(f"destination is not a regular file: {destination.name}")
            if destination.read_bytes() != source_bytes:
                raise TransformError(f"collision with different bytes: {destination.name}")
        else:
            destination.write_bytes(source_bytes)
            if destination.read_bytes() != source_bytes:
                raise TransformError(f"destination verification failed: {destination.name}")
        source.unlink()
        try:
            source_dir.rmdir()
        except OSError as exc:
            raise TransformError(f"source directory is not empty: {source_dir.name}") from exc
        changed.update({destination.name, f"{source_dir.name}/index.html"})
        redirect_names.append(source_dir.name)
        moved += 1
    existing_names = [
        path.stem
        for path in root.glob("cubicle-*.html")
        if path.is_file() and not path.is_symlink() and NAME_RE.fullmatch(path.stem)
    ]
    add_redirects(root, sorted(set(redirect_names + existing_names)), changed)
    return sorted(changed), {"mode": "flatten", "moved": moved}


def normalize_css(root: Path) -> tuple[list[str], dict[str, int]]:
    changed: set[str] = set()
    normalized = 0
    checked = 0
    for path in sorted(root.glob("cubicle-*.html"), key=lambda item: item.name):
        text, bom = read_text(path)
        for match in STYLESHEET_RE.finditer(text):
            href_match = HREF_RE.search(match.group("tag"))
            if not href_match:
                continue
            href = href_match.group("href")
            if href.startswith(("http://", "https://", "//", "#")):
                continue
            if href.startswith("../wp-content/"):
                asset = root / href.removeprefix("../")
                checked += 1
                if not asset.is_file():
                    raise TransformError(f"stylesheet target missing: {path.name}: {href}")
            elif href.startswith("wp-content/"):
                asset = root / href
                checked += 1
                if not asset.is_file():
                    raise TransformError(f"stylesheet target missing: {path.name}: {href}")
        replacements = 0

        def normalize_stylesheet(match: re.Match[str]) -> str:
            nonlocal replacements
            tag, count = WP_CONTENT_RE.subn(r"\1wp-content/", match.group(0))
            replacements += count
            return tag

        new_text = STYLESHEET_RE.sub(normalize_stylesheet, text)
        if replacements:
            write_text(path, new_text, bom)
            changed.add(path.name)
            normalized += replacements
    return sorted(changed), {"mode": "css", "normalized": normalized, "checked": checked}


def verify_git(root: Path, paths_file: Path) -> dict[str, int]:
    expected = [item for item in paths_file.read_text(encoding="utf-8").split("\0") if item]
    observed_raw = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    observed = observed_raw.rstrip(b"\0").decode("utf-8").split("\0") if observed_raw else []
    if observed != expected:
        raise TransformError(f"staged path boundary mismatch: expected {expected}, observed {observed}")
    return {"staged": len(observed)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("flatten", "css", "verify-git"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--paths-file", type=Path)
    parser.add_argument("--summary-file", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.mode == "verify-git":
        if not args.paths_file:
            raise SystemExit("--paths-file is required")
        summary = verify_git(root, args.paths_file)
    else:
        changed, summary = flatten(root) if args.mode == "flatten" else normalize_css(root)
        if args.paths_file:
            args.paths_file.write_text("\0".join(changed) + ("\0" if changed else ""), encoding="utf-8")
        summary["changed"] = len(changed)
    if args.summary_file:
        args.summary_file.write_text(json.dumps(summary, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
