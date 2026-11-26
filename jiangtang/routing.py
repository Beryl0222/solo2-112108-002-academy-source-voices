"""收听路径的校验、短听桥接与影响面分析。

开放路径上的每一次交付都必须自洽：代词有前文、反驳有对象、
预算不超限。访问级别在路线选择时确定：scholar 是馆内深听、
public 是普通导览；工具不会把不在路径开放范围内的稿片挪进来，
因此深度材料不会被塞进短听凑时长。
"""
from __future__ import annotations

from .discourse import check_path_sequence

# 访问级别排序，供跨级别规则扩展使用；当前资料的级别由路由自带。
_AUDIENCE_RANK = {"public": 1, "scholar": 2}


class RouteError(ValueError):
    """路径结构性错误（引用不存在、级别越界等）。"""


def route_duration(library, fragment_ids):
    return sum(library.fragment_by_id[identifier]["dur_s"] for identifier in fragment_ids)


def validate_structure(library, route):
    """引用、重复片与预算的结构检查。"""
    errors = []
    fragment_ids = route["ids"]
    if len(fragment_ids) != len(set(fragment_ids)):
        errors.append("路径内稿片重复")
    for identifier in fragment_ids + list(route["allowed_bridge"]):
        if identifier not in library.fragment_by_id:
            errors.append(f"稿片 {identifier} 不存在")
    duration = route_duration(library, fragment_ids)
    if duration > route["budget_s"]:
        errors.append(
            f"估时 {duration}s 超过路径预算 {route['budget_s']}s"
        )
    return errors


def needed_bridges(library, classified, route, sequence=None):
    """根据指代/反驳缺口，从 allowed_bridge 中挑出必须插入的串词。

    只允许使用路径声明过的串词；没有合适串词时返回缺口本身，
    交编辑决定是否写经批准的短桥接句。
    """
    sequence = sequence or list(route["ids"])
    findings = check_path_sequence(classified, sequence, route["id"])
    blocked = [item for item in findings if item["status"] == "block"]
    chosen = []
    unresolved = []
    for item in blocked:
        bridge = _pick_bridge(library, route, item)
        if bridge is None:
            unresolved.append(item)
        elif bridge not in chosen:
            chosen.append(bridge)
    return chosen, unresolved


def _pick_bridge(library, route, blocked_item):
    """在允许的串词里找字面覆盖缺口代词或反驳对象的一条。"""
    for bridge_id in route["allowed_bridge"]:
        bridge = library.fragment_by_id[bridge_id]
        if blocked_item["check"] == "anaphora":
            if blocked_item.get("pronoun") and blocked_item["pronoun"] in bridge["text"]:
                return bridge_id
        if blocked_item["check"] == "rebuttal":
            # 串词重述了被删铺垫里的主张即可补前提。
            if any(term in bridge["text"] for term in ("旧书", "读尽", "入门")):
                return bridge_id
    return None


def evaluate_route(library, classified, route):
    """对一条开放路径做完整校验，返回结构化报告。"""
    report = {
        "route": route["id"],
        "label": route["label"],
        "audience": route["audience"],
        "sequence": list(route["ids"]),
        "duration_s": route_duration(library, route["ids"]),
        "budget_s": route["budget_s"],
        "errors": validate_structure(library, route),
        "bridges": [],
        "unresolved": [],
        "checks": [],
    }
    if report["errors"]:
        return report

    bridges, unresolved = needed_bridges(library, classified, route)
    playable_sequence = list(route["ids"])
    for bridge_id, before_id in _bridge_insertion_points(library, route, bridges):
        position = (
            playable_sequence.index(before_id)
            if before_id in playable_sequence
            else 0
        )
        playable_sequence.insert(position, bridge_id)
    report["bridges"] = bridges
    report["unresolved"] = unresolved
    report["playable_sequence"] = playable_sequence
    report["playable_duration_s"] = route_duration(library, playable_sequence)
    if report["playable_duration_s"] > route["budget_s"]:
        report["errors"].append(
            f"补入串词后估时 {report['playable_duration_s']}s 超过预算 {route['budget_s']}s"
        )
    report["checks"] = check_path_sequence(
        classified, playable_sequence, route["id"]
    )
    report["playable"] = not report["errors"] and not report["unresolved"] and not any(
        item["status"] == "block" for item in report["checks"]
    )
    return report


def _bridge_insertion_points(library, route, bridges):
    """串词必须插在它所服务的稿片之前：先补前提，再让代词出现。"""
    points = []
    for bridge_id in bridges:
        before_id = route["ids"][0] if route["ids"] else None
        for fragment_id in route["ids"]:
            fragment = library.fragment_by_id[fragment_id]
            if any(pronoun in fragment["text"] for pronoun in ("它", "其", "那种")):
                before_id = fragment_id
                break
        points.append((bridge_id, before_id))
    return points


def shorten_proposal(library, classified, route, drop_ids):
    """编辑点选要删的铺垫片，工具校验短听是否仍自洽。

    删片只能从路径正片中选；深度材料不在本路径开放范围内，
    不会被挪进来凑时长。
    """
    dropped = [identifier for identifier in drop_ids if identifier in route["ids"]]
    illegal = [identifier for identifier in drop_ids if identifier not in route["ids"]]
    if illegal:
        raise RouteError(
            f"短听只能删本路径正片，{illegal} 不在 {route['id']} 中"
        )
    short_sequence = [
        identifier for identifier in route["ids"] if identifier not in dropped
    ]
    bridges, unresolved = needed_bridges(
        library, classified, route, sequence=short_sequence
    )
    playable_sequence = list(short_sequence)
    for bridge_id in bridges:
        playable_sequence.insert(0, bridge_id)
    duration = route_duration(library, playable_sequence)
    findings = check_path_sequence(classified, playable_sequence, route["id"])
    return {
        "route": route["id"],
        "dropped": dropped,
        "short_sequence": short_sequence,
        "bridges": bridges,
        "playable_sequence": playable_sequence,
        "duration_s": duration,
        "within_budget": duration <= route["budget_s"],
        "unresolved": unresolved,
        "checks": findings,
        "playable": not unresolved
        and duration <= route["budget_s"]
        and not any(item["status"] == "block" for item in findings),
    }


def impact_of_fragment(library, fragment_id):
    """反查一片被哪些路径（正片或可插串词）使用。

    改动说话人或断言范围后，这些路径都要重审；未引用它的路径无影响，
    已批准且未受影响的路径保持可播。
    """
    usage = []
    for route in library.routes:
        role = None
        if fragment_id in route["ids"]:
            role = "正片"
        elif fragment_id in route["allowed_bridge"]:
            role = "可插串词"
        if role:
            usage.append(
                {
                    "route": route["id"],
                    "label": route["label"],
                    "audience": route["audience"],
                    "role": role,
                }
            )
    return usage


def stale_approvals(library, workspace, approvals=None):
    """批准时逐 span 锁定的稿本号落后于当前判词，即为待重审。

    只列出该路径实际用到、且确实被改动过的 span；改了别的 span
    的路径不受影响，保持可播。
    """
    approvals = library.load_approvals(workspace) if approvals is None else approvals
    annotations = library.load_annotations(workspace)
    current = {}
    for (fragment_id, span_index), row in annotations.items():
        current.setdefault(fragment_id, {})[span_index] = row["revision"]

    stale = []
    for approval in approvals:
        route = library.route_by_id[approval["route"]]
        for fragment_id in route["ids"]:
            locked = approval.get("span_revisions", {}).get(fragment_id, {})
            for span_index, revision in current.get(fragment_id, {}).items():
                locked_revision = locked.get(str(span_index), 1)
                if revision > locked_revision:
                    stale.append(
                        {
                            "route": route["id"],
                            "fragment": fragment_id,
                            "span": span_index,
                            "locked_revision": locked_revision,
                            "current_revision": revision,
                        }
                    )
    return stale
