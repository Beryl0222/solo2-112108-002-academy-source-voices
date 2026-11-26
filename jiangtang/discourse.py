"""争议检测、跨轮指代与反驳对象检查。

相邻两轮问答允许跨轮补全指代；超出两轮的代词视为没有说得通的前文。
反问与对比反驳在去掉铺垫后，仍要能在同片或前两轮找到反驳对象。
"""
from __future__ import annotations

import re

from .classify import normalize

# 释义中表示“另一种讲法”的措辞。
_ALTERNATIVE_HINTS = ("或", "另", "异", "歧", "补写者", "也有")
_DISPUTE_TERMS_HINTS = ("两种意思", "两种理解", "或指", "分歧", "争议")

# 代词词表（合成业务用，按字匹配）。
_PRONOUNS = ("它", "那种", "其", "这里", "这话", "这个", "这一点")
# 凝固的四字文言表达，其中的“其”不承担路径指代。
_FIXED_CLASSICAL = ("待闻其事", "不闻其事", "勿归其言", "言归其")
# 讲解员直接解释指代的句式，视作桥接绑定。
_BINDING_HINTS = ("说的是", "指的是", "意思是")
# 反驳/对比标记。
_REBUT_HINTS = ("却", "不足", "只算", "反问", "怎能", "哪能", "么？", "吗？", "勿")
# 可充当前提主张的 span 性质。
_CLAIM_KINDS = {"opponent", "paraphrase", "quote", "question"}

_TERM_RE = re.compile(r"[一-鿿]{2,}")


def _content_terms(text):
    """粗抽两字以上的中文词，用于争议与稿片的语义挂靠。"""
    stopwords = {"这里", "一种", "意思", "可以", "理解", "认为", "所谓"}
    return {term for term in _TERM_RE.findall(text) if term not in stopwords}


def find_disputes(library):
    """找出同一文献下互不相让的释义对。

    规则：两条释义同属一部文献，且至少一条带“另讲”标记（或/另/异/补写者），
    即列为争议。争议是释义层面的分歧，不允许合并成同一位古人的话。
    """
    interpretations = [row for row in library.witnesses if row["type"] == "释义"]
    disputes = []
    for pos, left in enumerate(interpretations):
        for right in interpretations[pos + 1:]:
            if left["work"] != right["work"]:
                continue
            marked = any(
                hint in left["text"] or hint in right["text"]
                for hint in _ALTERNATIVE_HINTS
            )
            if not marked:
                continue
            disputes.append(
                {
                    "work": left["work"],
                    "readings": [
                        {
                            "key": library.cite_key(left),
                            "speaker": left["speaker"],
                            "text": left["text"],
                        },
                        {
                            "key": library.cite_key(right),
                            "speaker": right["speaker"],
                            "text": right["text"],
                        },
                    ],
                    "terms": sorted(
                        _content_terms(left["text"]) & _content_terms(right["text"])
                    ),
                }
            )
    return disputes


def fragments_touching_dispute(library, disputes):
    """把争议挂到提到同一组词的稿片上，供编辑逐片裁决。"""
    mapping = {dispute["work"]: dispute for dispute in disputes}
    touched = {}
    for fragment in library.script:
        fragment_terms = _content_terms(fragment["text"])
        mentions_dispute = any(
            hint in fragment["text"] for hint in _DISPUTE_TERMS_HINTS
        )
        for work, dispute in mapping.items():
            shared = fragment_terms & set(dispute["terms"])
            if mentions_dispute or shared:
                touched.setdefault(fragment["id"], []).append(
                    {"work": work, "shared_terms": sorted(shared)}
                )
    return touched


def _span_pronouns(span):
    pronouns = [word for word in _PRONOUNS if word in span.text]
    if "其" in pronouns and any(phrase in span.text for phrase in _FIXED_CLASSICAL):
        pronouns.remove("其")
    return pronouns


def _binding_targets(span):
    """讲解员串词里“X 说的是 Y”直接给出指代所指。"""
    if span.kind != "narrator":
        return {}
    targets = {}
    for pronoun in _PRONOUNS:
        if pronoun in span.text and any(hint in span.text for hint in _BINDING_HINTS):
            targets[pronoun] = span.text
    return targets


def _is_rebuttal(span):
    return span.kind == "question" or any(hint in span.text for hint in _REBUT_HINTS)


def check_path_sequence(classified, sequence, route_id):
    """按开放收听顺序检查一条路径上的指代与反驳是否自洽。

    sequence 是稿片 id 的有序列表（含被批准插入的串词）。
    只回看相邻两轮（当前片与前一片），符合“相邻两轮跨轮补全”的口径。
    同片内先出现的对手主张立即可供后出现的反问作为对象；
    整条路径的第一问按开场设问处理，不要求前文。
    """
    findings = []
    # 已出现的实体：用非代词 span 的归一化字面粗建。
    recent_terms = []
    recent_claims = []
    bound = {}
    seen_any_span = False

    for order, fragment_id in enumerate(sequence):
        spans = classified.get(fragment_id, ())
        for span in spans:
            for pronoun, target in _binding_targets(span).items():
                bound[pronoun] = {
                    "resolved_by": fragment_id,
                    "antecedent_text": target,
                }
            # 逐字引文内部的代词属于被引原文，由出处负责，不做路径指代检查。
            if span.kind != "quote":
                for pronoun in _span_pronouns(span):
                    if pronoun in bound:
                        findings.append(
                            {
                                "route": route_id,
                                "fragment": fragment_id,
                                "span": span.index,
                                "check": "anaphora",
                                "status": "ok",
                                "pronoun": pronoun,
                                "antecedent": bound[pronoun],
                            }
                        )
                        continue
                    antecedent = _find_antecedent(pronoun, recent_terms)
                    if antecedent is None:
                        findings.append(
                            {
                                "route": route_id,
                                "fragment": fragment_id,
                                "span": span.index,
                                "check": "anaphora",
                                "status": "block",
                                "pronoun": pronoun,
                                "message": (
                                    f"代词「{pronoun}」在前两轮找不到说得通的前文，"
                                    "需补 allowed_bridge 内的串词"
                                ),
                            }
                        )
                    else:
                        findings.append(
                            {
                                "route": route_id,
                                "fragment": fragment_id,
                                "span": span.index,
                                "check": "anaphora",
                                "status": "ok",
                                "pronoun": pronoun,
                                "antecedent": antecedent,
                            }
                        )
            if _is_rebuttal(span):
                target = _find_rebuttal_target(span, recent_claims)
                if target is None and not seen_any_span:
                    findings.append(
                        {
                            "route": route_id,
                            "fragment": fragment_id,
                            "span": span.index,
                            "check": "rebuttal",
                            "status": "ok",
                            "target": None,
                            "note": "开场设问，不要求前文反驳对象",
                        }
                    )
                elif target is None:
                    findings.append(
                        {
                            "route": route_id,
                            "fragment": fragment_id,
                            "span": span.index,
                            "check": "rebuttal",
                            "status": "block",
                            "message": (
                                "去掉铺垫后反驳没有清楚的反驳对象，"
                                "需保留对手主张或经编辑同意的短桥接句"
                            ),
                        }
                    )
                else:
                    findings.append(
                        {
                            "route": route_id,
                            "fragment": fragment_id,
                            "span": span.index,
                            "check": "rebuttal",
                            "status": "ok",
                            "target": target,
                        }
                    )

            # 同片内先出现的 span 立即进入窗口，供后续 span 回指。
            entry = {
                "fragment": fragment_id,
                "span": span.index,
                "text": span.text,
                "kind": span.kind,
            }
            recent_terms.append(entry)
            if span.kind in _CLAIM_KINDS:
                recent_claims.append(entry)
            seen_any_span = True

        # 刷新“相邻两轮”窗口：只保留当前片与前一片。
        cutoff_fragment = sequence[max(0, order - 1)]
        recent_terms = [
            item
            for item in recent_terms
            if item["fragment"] in (fragment_id, cutoff_fragment)
        ][-12:]
        recent_claims = [
            item
            for item in recent_claims
            if item["fragment"] in (fragment_id, cutoff_fragment)
        ][-8:]

    return findings


def _find_antecedent(pronoun, recent_terms):
    """在前两轮窗口里找非代词、非纯串词的实体。"""
    for item in reversed(recent_terms):
        if item["kind"] == "narrator":
            continue
        if pronoun in normalize(item["text"]):
            continue
        if normalize(item["text"]):
            return item
    return None


def _find_rebuttal_target(span, recent_claims):
    """反驳对象优先是对手主张，其次是前两轮里的任一实质主张。"""
    for item in reversed(recent_claims):
        if item["kind"] == "opponent":
            return item
    for item in reversed(recent_claims):
        if item["fragment"] == span.fragment and item["span"] == span.index:
            continue
        return item
    return None
