"""书院导读朗读编审工具。

模块划分：
- io        业务资料与工作目录读写
- classify  字句切分与逐字/概述/反问/转述/串词初判
- discourse 争议、跨轮指代与反驳对象
- routing   路径校验、短听桥接、预算与影响面
- editorial 判词、批准与文献版本管理
- delivery  播控自洽交付与历史留档
"""
from .io import Library, Workspace
from .classify import apply_judgments, classify_all, split_spans
from .discourse import find_disputes, fragments_touching_dispute
from .routing import (
    evaluate_route,
    impact_of_fragment,
    shorten_proposal,
    stale_approvals,
)
from .editorial import (
    adjudicate,
    approval_status,
    approve_route,
    superseded_witnesses,
)
from .delivery import build_delivery, write_delivery

__all__ = [
    "Library",
    "Workspace",
    "apply_judgments",
    "classify_all",
    "split_spans",
    "find_disputes",
    "fragments_touching_dispute",
    "evaluate_route",
    "impact_of_fragment",
    "shorten_proposal",
    "stale_approvals",
    "adjudicate",
    "approval_status",
    "approve_route",
    "superseded_witnesses",
    "build_delivery",
    "write_delivery",
]
