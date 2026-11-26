"""编辑判词、路径批准与文献更正的版本管理。

判词与批准只写入工作目录；原来源被更正后，旧版交付保留在内部
deliveries 中可供核对当年录过什么，前台新交付不得沿用旧归因。
"""
from __future__ import annotations

from datetime import date

from .classify import validate_judgment
from .routing import impact_of_fragment, stale_approvals


def adjudicate(
    library,
    workspace,
    judgment_id,
    fragment_id,
    span_index,
    kind,
    speaker,
    authority,
    evidence=None,
    notes=None,
):
    """落一条编辑判词，改判角色或性质，并把该片稿本号加一。"""
    span_text = validate_judgment(
        library, workspace, fragment_id, span_index, kind, speaker, evidence or []
    )
    annotations = library.load_annotations(workspace)
    key = (fragment_id, span_index)
    validate_duplicate = annotations.get(key)
    # 交入稿本号为 1；每一次编辑判词都使整片稿本号向前推一号，
    # 同片不同 span 的判词共享同一条单调递增的稿本线。
    current = library.fragment_revision(workspace, fragment_id)
    revision = current + 1
    annotations[key] = {
        "id": judgment_id,
        "fragment": fragment_id,
        "span": span_index,
        "kind": kind,
        "speaker": speaker,
        "authority": authority,
        "revision": revision,
        "evidence": evidence or [],
        "notes": list(notes or []),
        "span_text": span_text,
    }
    library.save_annotations(workspace, annotations)
    return {
        "judgment": judgment_id,
        "fragment": fragment_id,
        "span": span_index,
        "revision": revision,
        "replaced": validate_duplicate["id"] if validate_duplicate else None,
        "impacted_routes": impact_of_fragment(library, fragment_id),
    }


def approve_route(library, workspace, route_id, authority, note, today=None):
    """批准单条收听路径，逐 span 锁定当前稿本号。"""
    if route_id not in library.route_by_id:
        raise ValueError(f"路径 {route_id} 不存在")
    annotations = library.load_annotations(workspace)
    span_revisions = {}
    for fragment_id in library.route_by_id[route_id]["ids"]:
        # 未编辑过的 span 仍停留在交入稿本 1。
        per_span = {}
        for key, row in annotations.items():
            if key[0] == fragment_id:
                per_span[str(key[1])] = row["revision"]
        span_revisions[fragment_id] = per_span
    record = {
        "route": route_id,
        "authority": authority,
        "note": note,
        "span_revisions": span_revisions,
        "at": (today or date.today()).isoformat(),
    }
    approvals = library.load_approvals(workspace)
    approvals = [row for row in approvals if row["route"] != route_id]
    approvals.append(record)
    library.save_approvals(workspace, approvals)
    return record


def approval_status(library, workspace):
    """汇总每条路径的批准与待重审状态。"""
    approvals = {row["route"]: row for row in library.load_approvals(workspace)}
    stale_routes = {item["route"] for item in stale_approvals(library, workspace)}
    statuses = []
    for route in library.routes:
        approval = approvals.get(route["id"])
        if approval is None:
            state = "未批准"
        elif route["id"] in stale_routes:
            state = "批准已过期，待重审"
        else:
            state = "批准有效"
        statuses.append(
            {
                "route": route["id"],
                "label": route["label"],
                "state": state,
                "approval": approval,
            }
        )
    return statuses


def superseded_witnesses(library, today=None):
    """校记生效后，同文献同页的旧录文转为存查，不得再用于新交付。"""
    today = today or date.today()
    superseded = {}
    for witness, review in library.effective_today(today):
        for older in library.witnesses:
            if older["id"] == witness["id"]:
                continue
            if (
                older["work"] == witness["work"]
                and older["page"] == witness["page"]
                and older["type"] == "录文"
                and older["edition"] < witness["edition"]
            ):
                superseded[older["id"]] = {
                    "witness": older,
                    "superseded_by": witness,
                    "review": review["id"],
                }
    return superseded
