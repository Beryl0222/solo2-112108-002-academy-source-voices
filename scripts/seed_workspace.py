"""把已有业务签字（h1/h2/h3）落成工具工作目录里的结构化初始状态。

只引用 data/ 中的合成资料，可重复执行：每次先清空工作目录再重建。
运行：python3 -I scripts/seed_workspace.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jiangtang.editorial import adjudicate, approve_route
from jiangtang.io import Library, Workspace


def main():
    library = Library(ROOT / "data")
    workspace = Workspace(ROOT / "work")
    for path in (workspace.annotations_path, workspace.approvals_path):
        if path.exists():
            path.unlink()

    # h1：g3 为现代重述，原稿没有用引号（两个 span 都落判词）。
    adjudicate(
        library, workspace, "j1", "g3", 0, "paraphrase", "先生",
        "馆方编辑", notes=["对应 h1：现代重述，原稿没有用引号"],
    )
    adjudicate(
        library, workspace, "j2", "g3", 1, "paraphrase", "先生",
        "馆方编辑", notes=["对应 h1：现代重述，原稿没有用引号"],
    )
    # h3：g5 可作逐字引文，出处回点手札录文 e4（3c）。
    adjudicate(
        library, workspace, "j3", "g5", 0, "quote", "沈生",
        "馆方编辑",
        evidence=[{"key": library.cite_key(library.witness_by_id["e4"]), "use": "录文"}],
        notes=["对应 h3：手札 3c 可作逐字引文"],
    )
    adjudicate(
        library, workspace, "j4", "g5", 1, "quote", "沈生",
        "馆方编辑",
        evidence=[{"key": library.cite_key(library.witness_by_id["e4"]), "use": "录文"}],
        notes=["对应 h3：手札 3c 可作逐字引文"],
    )
    # h2：r1 已录，按入门站整路线领稿。
    approve_route(
        library, workspace, "r1", "播控编辑",
        "对应 h2：已录，按入门站整路线领稿",
    )
    print("seeded:", sorted(p.name for p in workspace.root.iterdir()))


if __name__ == "__main__":
    main()
