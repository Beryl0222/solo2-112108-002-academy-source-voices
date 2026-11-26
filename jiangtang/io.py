"""资料与编审状态的读写。

业务资料（data/）是编辑交入的交换文件，本模块只做读取与字段核对；
工具自身产生的判词、路径批准与交付记录写到独立工作目录（work/），
两者互不覆盖。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

WITNESSES = "witnesses"
SCRIPT = "script"
ROUTES = "routes"
REVIEWS = "reviews"
COLLECTIONS = (WITNESSES, SCRIPT, ROUTES, REVIEWS)

ANNOTATIONS_FILE = "annotations.jsonl"
APPROVALS_FILE = "approvals.jsonl"


def read_collection(directory, name):
    """用资料索引核对并读取单份 UTF-8 JSONL 记录集合。"""
    root = Path(directory)
    manifest = json.loads((root / "index.json").read_text(encoding="utf-8"))
    if name not in manifest:
        raise KeyError(f"资料索引中没有集合 {name}")
    fields = set(manifest[name])
    path = root / (name + ".jsonl")
    rows = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{name} 第 {line_number} 行不是有效的 JSON") from error
            if not isinstance(record, dict) or set(record.keys()) != fields:
                raise ValueError(f"{name} 第 {line_number} 行与资料索引不符")
            rows.append(record)
    return rows


def _read_jsonl(path):
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path.name} 第 {line_number} 行不是有效的 JSON") from error
            rows.append(record)
    return rows


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as target:
        for row in rows:
            target.write(json.dumps(row, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class Workspace:
    """工具工作目录，保存判词、批准与交付，不与交入资料混放。"""

    root: Path

    def __post_init__(self):
        object.__setattr__(self, "root", Path(self.root))

    @property
    def annotations_path(self):
        return self.root / ANNOTATIONS_FILE

    @property
    def approvals_path(self):
        return self.root / APPROVALS_FILE

    @property
    def deliveries_dir(self):
        return self.root / "deliveries"


class Library:
    """装入并索引全部业务资料，提供按 id 与出处回点。"""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.witnesses = read_collection(self.data_dir, WITNESSES)
        self.script = read_collection(self.data_dir, SCRIPT)
        self.routes = read_collection(self.data_dir, ROUTES)
        self.reviews = read_collection(self.data_dir, REVIEWS)
        self.witness_by_id = {row["id"]: row for row in self.witnesses}
        self.fragment_by_id = {row["id"]: row for row in self.script}
        self.route_by_id = {row["id"]: row for row in self.routes}
        self._validate_references()

    def _validate_references(self):
        fragment_ids = set(self.fragment_by_id)
        witness_ids = set(self.witness_by_id)
        for route in self.routes:
            for identifier in route["ids"]:
                if identifier not in fragment_ids:
                    raise ValueError(f"路径 {route['id']} 引用了不存在的稿片 {identifier}")
            for identifier in route["allowed_bridge"]:
                if identifier not in fragment_ids:
                    raise ValueError(
                        f"路径 {route['id']} 的串词 {identifier} 不是已有稿片"
                    )
            overlap = set(route["ids"]) & set(route["allowed_bridge"])
            if overlap:
                raise ValueError(
                    f"路径 {route['id']} 中 {sorted(overlap)} 同时是正片与串词"
                )
        for fragment in self.script:
            if not self._anchor_witnesses(fragment["anchor"]):
                raise ValueError(
                    f"稿片 {fragment['id']} 的线索页 {fragment['anchor']} 没有对应录文或校记"
                )
        for review in self.reviews:
            subject = review["subject"]
            if subject not in fragment_ids and subject not in self.route_by_id:
                if subject not in witness_ids:
                    raise ValueError(f"签字 {review['id']} 的对象 {subject} 不存在")

    def _anchor_witnesses(self, page):
        return [row for row in self.witnesses if row["page"] == page]

    def cite_key(self, witness):
        """出处以 id、edition、page 合用，同一页不同文献不混用。"""
        return f"{witness['id']}@ed{witness['edition']}:{witness['page']}"

    def load_annotations(self, workspace):
        rows = _read_jsonl(workspace.annotations_path)
        by_span = {}
        for row in rows:
            if row["fragment"] not in self.fragment_by_id:
                raise ValueError(
                    f"判词指向不存在的稿片 {row['fragment']}"
                )
            by_span[(row["fragment"], row["span"])] = row
        return by_span

    def save_annotations(self, workspace, annotations):
        ordered = sorted(annotations.values(), key=lambda row: (row["fragment"], row["span"]))
        _write_jsonl(workspace.annotations_path, ordered)

    def load_approvals(self, workspace):
        rows = _read_jsonl(workspace.approvals_path)
        for row in rows:
            if row["route"] not in self.route_by_id:
                raise ValueError(f"批准记录指向不存在的路径 {row['route']}")
        return rows

    def save_approvals(self, workspace, approvals):
        _write_jsonl(workspace.approvals_path, approvals)

    def fragment_revision(self, workspace, fragment_id):
        """稿片被改判一次，稿本号加一；没有判词时沿用交入稿本 1。"""
        annotations = self.load_annotations(workspace)
        revisions = [
            row["revision"]
            for row in annotations.values()
            if row["fragment"] == fragment_id
        ]
        return max(revisions, default=1)

    def effective_today(self, today=None):
        """截至今日已到生效日的校记。"""
        today = today or date.today()
        effective = []
        for witness in self.witnesses:
            if witness["type"] != "校记":
                continue
            for review in self.reviews:
                if review["subject"] != witness["id"]:
                    continue
                at_day = date.fromisoformat(review["at"][:10])
                if at_day <= today:
                    effective.append((witness, review))
        return effective
