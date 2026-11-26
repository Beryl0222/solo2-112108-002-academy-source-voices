"""编审工具命令行。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from .classify import apply_judgments, classify_all
from .delivery import write_delivery
from .discourse import find_disputes, fragments_touching_dispute
from .editorial import (
    adjudicate,
    approval_status,
    approve_route,
    superseded_witnesses,
)
from .io import Library, Workspace, read_collection
from .routing import evaluate_route, impact_of_fragment, shorten_proposal


def _print(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _evidence_items(library, witness_ids):
    items = []
    for witness_id in witness_ids or []:
        witness = library.witness_by_id[witness_id]
        items.append(
            {
                "key": library.cite_key(witness),
                "use": witness["type"],
            }
        )
    return items


def _classified(library, workspace):
    return apply_judgments(library, workspace, classify_all(library))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="jiangtang",
        description="书院导读引文、转述与反驳的朗读编审工具",
    )
    parser.add_argument("--data", default="data", help="业务资料目录")
    parser.add_argument("--work", default="work", help="编审工作目录")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="核对业务资料字段与引用")

    p_classify = sub.add_parser("classify", help="查看稿片字句初判与编辑判词")
    p_classify.add_argument("fragment", nargs="?", help="只看指定稿片")

    sub.add_parser("disputes", help="列出释义分歧及挂靠稿片，分歧交编辑裁决")

    p_routes = sub.add_parser("routes", help="逐条校验开放收听路径")
    p_routes.add_argument("route", nargs="?")

    p_short = sub.add_parser("shorten", help="点选铺垫片试算短听走法")
    p_short.add_argument("route")
    p_short.add_argument("--drop", nargs="+", required=True, help="要删的铺垫稿片")

    p_impact = sub.add_parser("impact", help="反查稿片被哪些路径使用")
    p_impact.add_argument("fragment")

    p_judge = sub.add_parser("adjudicate", help="按来源页码证据改判字句角色或性质")
    p_judge.add_argument("--id", required=True, help="判词号")
    p_judge.add_argument("--fragment", required=True)
    p_judge.add_argument("--span", required=True, type=int)
    p_judge.add_argument(
        "--kind",
        required=True,
        choices=["quote", "paraphrase", "question", "opponent", "narrator"],
    )
    p_judge.add_argument("--speaker", required=True)
    p_judge.add_argument("--authority", required=True)
    p_judge.add_argument("--evidence", nargs="*", default=[], help="回点的文献 id")
    p_judge.add_argument("--note", action="append", default=[])

    p_approve = sub.add_parser("approve", help="批准单条收听路径并锁定稿本号")
    p_approve.add_argument("route")
    p_approve.add_argument("--authority", required=True)
    p_approve.add_argument("--note", default="")

    p_deliver = sub.add_parser("deliver", help="生成播控自洽交付并留档")
    p_deliver.add_argument("route")
    p_deliver.add_argument("--strict", action="store_true", help="未批准有效则拒绝交付")
    p_deliver.add_argument("--today", help="覆盖当前日期 YYYY-MM-DD，供测试")

    sub.add_parser("status", help="查看批准状态与被更正存查的旧录文")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    library = Library(args.data)
    workspace = Workspace(args.work)

    if args.command == "check":
        _print(
            {name: len(read_collection(args.data, name)) for name in
             ("witnesses", "script", "routes", "reviews")}
        )
        return 0

    if args.command == "classify":
        classified = _classified(library, workspace)
        payload = {
            fragment_id: [span.to_record() for span in spans]
            for fragment_id, spans in classified.items()
            if args.fragment is None or fragment_id == args.fragment
        }
        if args.fragment and args.fragment not in payload:
            parser.error(f"稿片 {args.fragment} 不存在")
        _print(payload)
        return 0

    if args.command == "disputes":
        disputes = find_disputes(library)
        _print(
            {
                "disputes": disputes,
                "touched_fragments": fragments_touching_dispute(library, disputes),
                "rule": "两种释义都讲得通时交编辑裁决，不得揉成同一位古人的话",
            }
        )
        return 0

    if args.command == "routes":
        classified = _classified(library, workspace)
        targets = (
            [library.route_by_id[args.route]]
            if args.route
            else library.routes
        )
        if args.route and not targets:
            parser.error(f"路径 {args.route} 不存在")
        _print([evaluate_route(library, classified, route) for route in targets])
        return 0

    if args.command == "shorten":
        route = library.route_by_id.get(args.route)
        if route is None:
            parser.error(f"路径 {args.route} 不存在")
        classified = _classified(library, workspace)
        _print(shorten_proposal(library, classified, route, args.drop))
        return 0

    if args.command == "impact":
        if args.fragment not in library.fragment_by_id:
            parser.error(f"稿片 {args.fragment} 不存在")
        _print(
            {
                "fragment": args.fragment,
                "usage": impact_of_fragment(library, args.fragment),
                "rule": "改动说话人或断言范围后列出的路径须重审，无影响路径保持可播",
            }
        )
        return 0

    if args.command == "adjudicate":
        result = adjudicate(
            library,
            workspace,
            judgment_id=args.id,
            fragment_id=args.fragment,
            span_index=args.span,
            kind=args.kind,
            speaker=args.speaker,
            authority=args.authority,
            evidence=_evidence_items(library, args.evidence),
            notes=args.note,
        )
        _print(result)
        return 0

    if args.command == "approve":
        _print(approve_route(library, workspace, args.route, args.authority, args.note))
        return 0

    if args.command == "deliver":
        today = date.fromisoformat(args.today) if args.today else None
        classified = _classified(library, workspace)
        path, delivery = write_delivery(
            library, workspace, args.route, classified, today=today, strict=args.strict
        )
        _print({"written": str(path), "delivery": delivery})
        return 0 if delivery["playable"] else 1

    if args.command == "status":
        _print(
            {
                "approvals": approval_status(library, workspace),
                "superseded_witnesses": [
                    {
                        "witness": key,
                        "by": item["superseded_by"]["id"],
                        "review": item["review"],
                    }
                    for key, item in superseded_witnesses(library).items()
                ],
            }
        )
        return 0

    parser.error(f"未知命令 {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
