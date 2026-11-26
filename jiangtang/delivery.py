"""面向播控的自洽交付与历史留档。

每条可播稿是一次自洽交付：含角色、可朗读正文与出处提示。
被更正文献替代的旧录文不得进入新交付；历史交付原样留档，
内部可核对当年录过什么，前台不会把旧归因混进新交付。
"""
from __future__ import annotations

import json
from datetime import date

from .editorial import approval_status, superseded_witnesses
from .routing import evaluate_route


def _span_payload(span, superseded):
    evidence = []
    blocked_quote = False
    for item in span.evidence:
        witness_id = item["key"].split("@", 1)[0]
        if witness_id in superseded:
            if span.kind == "quote":
                blocked_quote = True
            evidence.append({**item, "status": "superseded", "use": "仅供内部核对"})
        else:
            evidence.append({**item, "status": "current"})
    return {
        "span": span.index,
        "text": span.text,
        "kind": span.kind,
        "speaker": span.speaker,
        "evidence": evidence,
        "blocked_quote": blocked_quote,
    }


def build_delivery(library, workspace, route_id, classified, today=None, strict=False):
    """生成一条路径的播控交付字典。

    strict=True 时未批准路径不交付；默认仍出稿但标明批准状态，
    由播控端按状态决定是否上线。
    """
    today = today or date.today()
    route = library.route_by_id[route_id]
    report = evaluate_route(library, classified, route)
    superseded = superseded_witnesses(library, today)
    statuses = {item["route"]: item["state"] for item in approval_status(library, workspace)}
    approval_state = statuses[route_id]

    blocks = list(report["errors"])
    if report["unresolved"]:
        blocks.append("存在无法用 allowed_bridge 补足的指代/反驳缺口")
    if strict and approval_state != "批准有效":
        blocks.append(f"严格模式要求批准有效，当前状态：{approval_state}")

    items = []
    for fragment_id in report["playable_sequence"]:
        fragment = library.fragment_by_id[fragment_id]
        spans = [_span_payload(span, superseded) for span in classified[fragment_id]]
        for payload in spans:
            if payload.pop("blocked_quote"):
                blocks.append(
                    f"稿片 {fragment_id} 第 {payload['span']} 句的逐字出处已被更正，"
                    "新交付不得沿用旧归因，须重新回点"
                )
            # 片级建议朗读者与 span 级角色不同时显式提示，防止排期选错人。
            if payload["speaker"] != fragment["voice"]:
                payload["voice_conflict"] = (
                    f"片级建议朗读者为「{fragment['voice']}」，"
                    f"本句角色为「{payload['speaker']}」，排期以句角色为准"
                )
        items.append(
            {
                "fragment": fragment_id,
                "topic": fragment["topic"],
                "anchor": fragment["anchor"],
                "voice": fragment["voice"],
                "readable_text": fragment["text"],
                "spans": spans,
            }
        )

    delivery = {
        "delivery_of": route_id,
        "label": route["label"],
        "audience": route["audience"],
        "generated_on": today.isoformat(),
        "approval_state": approval_state,
        "playable": report["playable"] and not blocks,
        "blocks": blocks,
        "sequence": report["playable_sequence"],
        "duration_s": report["playable_duration_s"],
        "budget_s": route["budget_s"],
        "items": items,
        "superseded_evidence_kept_internal": sorted(superseded),
    }
    return delivery


def write_delivery(library, workspace, route_id, classified, today=None, strict=False):
    """写出新交付；历史交付不覆盖，按日期与序号留档。"""
    delivery = build_delivery(
        library, workspace, route_id, classified, today=today, strict=strict
    )
    directory = workspace.deliveries_dir
    directory.mkdir(parents=True, exist_ok=True)
    sequence = len(list(directory.glob(f"{route_id}_*.json"))) + 1
    name = f"{route_id}_{delivery['generated_on']}_{sequence}.json"
    path = directory / name
    path.write_text(
        json.dumps(delivery, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path, delivery
