"""编审工具的业务规则测试。

覆盖：字句分级与证据层级、争议不合并、跨轮指代与反驳、
短听桥接与预算、影响面与稿本重审、文献更正的版本隔离。
"""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jiangtang.classify import (
    apply_judgments,
    classify_all,
    normalize,
    split_spans,
)
from jiangtang.delivery import build_delivery
from jiangtang.discourse import (
    check_path_sequence,
    find_disputes,
    fragments_touching_dispute,
)
from jiangtang.editorial import (
    adjudicate,
    approval_status,
    approve_route,
    superseded_witnesses,
)
from jiangtang.io import Library, Workspace
from jiangtang.routing import (
    RouteError,
    evaluate_route,
    impact_of_fragment,
    shorten_proposal,
    stale_approvals,
)

DATA = ROOT / "data"


class ToolTestCase(unittest.TestCase):
    def setUp(self):
        self.library = Library(DATA)
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Workspace(self.temp.name)
        self.classified = apply_judgments(
            self.library, self.workspace, classify_all(self.library)
        )

    def tearDown(self):
        self.temp.cleanup()

    def kinds(self, fragment_id):
        return [(span.index, span.kind, span.speaker) for span in self.classified[fragment_id]]

    # ---- 字句分级 ----

    def test_spans_split_at_punctuation(self):
        self.assertEqual(
            split_spans("有人说尽读旧书就够了，这就能长进么？只算入门。"),
            ["有人说尽读旧书就够了，", "这就能长进么？", "只算入门。"],
        )

    def test_opponent_claim_not_attributed_to_master(self):
        # g1 前半句是待反驳的对手主张，不能读成先生的教诲。
        self.assertEqual(self.kinds("g1")[0], (0, "opponent", "问者/前人（转述对象）"))
        self.assertEqual(self.kinds("g1")[1][1], "question")
        self.assertEqual(self.kinds("g1")[2][1], "paraphrase")

    def test_quote_requires_record_witness(self):
        g5 = self.classified["g5"]
        self.assertTrue(all(span.kind == "quote" for span in g5))
        uses = {item["use"] for span in g5 for item in span.evidence}
        self.assertIn("录文", uses)
        self.assertNotIn("释义", uses)

    def test_interpretation_never_proves_quote(self):
        with self.assertRaises(ValueError) as context:
            adjudicate(
                self.library, self.workspace, "jx", "g6", 1,
                "quote", "先生", "馆方编辑",
                evidence=[{"key": "e2@ed1:18", "use": "释义"}],
            )
        self.assertIn("释义不能证明逐字引文", str(context.exception))

    def test_paraphrase_supported_by_interpretation_only(self):
        # g3 是现代重述，自动初判不得出现录文证据。
        for span in self.classified["g3"]:
            self.assertEqual(span.kind, "paraphrase")
            self.assertTrue(all(item["use"] == "释义" or not item["use"]
                                for item in span.evidence))

    def test_judgment_overrides_auto_classification(self):
        adjudicate(
            self.library, self.workspace, "j1", "g1", 1,
            "narrator", "讲解员", "馆方编辑",
        )
        merged = apply_judgments(
            self.library, self.workspace, classify_all(self.library)
        )
        span = merged["g1"][1]
        self.assertEqual(span.kind, "narrator")
        self.assertEqual(span.confidence, "adjudicated")

    # ---- 争议不合并 ----

    def test_two_readings_remain_separate(self):
        disputes = find_disputes(self.library)
        self.assertEqual(len(disputes), 1)
        readings = disputes[0]["readings"]
        self.assertEqual({r["speaker"] for r in readings}, {"校者沙", "校者兰"})
        self.assertNotEqual(readings[0]["text"], readings[1]["text"])
        touched = fragments_touching_dispute(self.library, disputes)
        self.assertIn("g4", touched)

    def test_dispute_fragment_carries_editor_warning(self):
        notes = " ".join(span.notes and " ".join(span.notes)
                         for span in self.classified["g4"])
        self.assertIn("分歧须交编辑", notes)

    # ---- 跨轮指代与反驳 ----

    def test_anaphora_resolved_across_adjacent_turns(self):
        report = evaluate_route(self.library, self.classified,
                                self.library.route_by_id["r1"])
        anaphora = [c for c in report["checks"] if c["check"] == "anaphora"]
        self.assertTrue(anaphora)
        self.assertTrue(all(c["status"] == "ok" for c in anaphora))
        ta = next(c for c in anaphora if c["fragment"] == "g3" and c["pronoun"] == "它")
        self.assertEqual(ta["antecedent"]["fragment"], "g1")

    def test_short_route_needs_allowed_bridge(self):
        route = self.library.route_by_id["r2"]
        bare = check_path_sequence(self.classified, list(route["ids"]), "r2")
        self.assertIn("block", [c["status"] for c in bare])
        report = evaluate_route(self.library, self.classified, route)
        self.assertEqual(report["bridges"], ["g2"])
        self.assertTrue(report["playable"])
        # 串词必须在代词出现之前。
        self.assertLess(
            report["playable_sequence"].index("g2"),
            report["playable_sequence"].index("g3"),
        )

    def test_bridge_outside_allowlist_cannot_be_used(self):
        # 构造一条只含 g3 且无任何串词的路由：代词缺口无法就地补足，
        # 工具只能保留 unresolved，不能擅自挪入未授权的稿片。
        route = {
            "id": "rx",
            "label": "无串词快听",
            "audience": "public",
            "ids": ["g3"],
            "allowed_bridge": [],
            "budget_s": 30,
        }
        report = evaluate_route(self.library, self.classified, route)
        self.assertTrue(report["unresolved"])
        self.assertFalse(report["playable"])
        self.assertEqual(report["playable_sequence"], ["g3"])

    def test_rebuttal_keeps_target_after_dropping_lead_in(self):
        route = self.library.route_by_id["r1"]
        proposal = shorten_proposal(
            self.library, self.classified, route, ["g0", "g1"]
        )
        self.assertTrue(proposal["playable"])
        self.assertIn("g2", proposal["playable_sequence"])
        rebuttals = [c for c in proposal["checks"] if c["check"] == "rebuttal"]
        self.assertTrue(rebuttals)
        self.assertTrue(all(c["status"] == "ok" for c in rebuttals))

    def test_cannot_drop_fragment_outside_route(self):
        with self.assertRaises(RouteError):
            shorten_proposal(
                self.library, self.classified,
                self.library.route_by_id["r1"], ["g4"],
            )

    def test_budget_enforced_with_bridge(self):
        route = self.library.route_by_id["r2"]
        report = evaluate_route(self.library, self.classified, route)
        self.assertLessEqual(report["playable_duration_s"], route["budget_s"])

    # ---- 影响面与稿本重审 ----

    def test_impact_lists_all_using_routes(self):
        usage = {item["route"] for item in impact_of_fragment(self.library, "g1")}
        self.assertEqual(usage, {"r1", "r3"})
        # r4 不引用 g1，改动对它无影响。
        self.assertNotIn("r4", usage)

    def test_approval_governed_per_span_revision(self):
        approve_route(self.library, self.workspace, "r1", "播控编辑", "领稿")
        # 改 r1 实际用到的 g1 span：批准应过期。
        adjudicate(self.library, self.workspace, "j9", "g1", 0,
                   "opponent", "问者", "馆方编辑")
        stale = {(s["route"], s["fragment"], s["span"])
                 for s in stale_approvals(self.library, self.workspace)}
        self.assertIn(("r1", "g1", 0), stale)
        states = {s["route"]: s["state"]
                  for s in approval_status(self.library, self.workspace)}
        self.assertEqual(states["r1"], "批准已过期，待重审")
        self.assertEqual(states["r4"], "未批准")

    def test_re_approval_restores_playable(self):
        approve_route(self.library, self.workspace, "r1", "播控编辑", "领稿")
        adjudicate(self.library, self.workspace, "j9", "g1", 0,
                   "opponent", "问者", "馆方编辑")
        self.assertFalse(
            build_delivery(self.library, self.workspace, "r1",
                           self.classified, strict=True)["playable"]
        )
        approve_route(self.library, self.workspace, "r1", "播控编辑", "重审通过")
        delivery = build_delivery(
            self.library, self.workspace, "r1",
            apply_judgments(self.library, self.workspace,
                            classify_all(self.library)),
            strict=True,
        )
        self.assertTrue(delivery["playable"])

    # ---- 文献更正与版本隔离 ----

    def test_correction_supersedes_old_record_only_after_effective_date(self):
        before = superseded_witnesses(self.library, today=date(2026, 11, 10))
        self.assertNotIn("e1", before)
        after = superseded_witnesses(self.library, today=date(2026, 11, 26))
        self.assertEqual(after["e1"]["superseded_by"]["id"], "e5")

    def test_new_delivery_flags_superseded_attribution(self):
        # 构造一条把 e1 当逐字出处的判词，新交付必须拦截。
        adjudicate(
            self.library, self.workspace, "jq", "g0", 1,
            "quote", "问者", "馆方编辑",
            evidence=[{"key": "e1@ed1:2a", "use": "录文"}],
        )
        classified = apply_judgments(
            self.library, self.workspace, classify_all(self.library)
        )
        delivery = build_delivery(
            self.library, self.workspace, "r1", classified,
            today=date(2026, 11, 26),
        )
        self.assertFalse(delivery["playable"])
        self.assertTrue(any("旧归因" in block for block in delivery["blocks"]))
        # 旧录文号只进入内部留档清单。
        self.assertIn("e1", delivery["superseded_evidence_kept_internal"])

    def test_delivery_is_self_contained(self):
        delivery = build_delivery(
            self.library, self.workspace, "r1", self.classified
        )
        for item in delivery["items"]:
            self.assertIn("voice", item)
            self.assertIn("readable_text", item)
            self.assertIn("anchor", item)
            for span in item["spans"]:
                self.assertIn("speaker", span)
                self.assertIn("text", span)
                self.assertIn("evidence", span)

    def test_delivery_flags_voice_conflict(self):
        # g5 片级 voice 是学者，确认引文的句角色是沈生。
        adjudicate(
            self.library, self.workspace, "jq5", "g5", 0,
            "quote", "沈生", "馆方编辑",
            evidence=[{"key": "e4@ed1:3c", "use": "录文"}],
        )
        classified = apply_judgments(
            self.library, self.workspace, classify_all(self.library)
        )
        delivery = build_delivery(
            self.library, self.workspace, "r1", classified
        )
        g5 = next(item for item in delivery["items"] if item["fragment"] == "g5")
        self.assertIn("voice_conflict", g5["spans"][0])

    def test_normalize_strips_punctuation_and_quotes(self):
        self.assertEqual(normalize("“它”，说的是……"), normalize("它说的是"))


if __name__ == "__main__":
    unittest.main()
