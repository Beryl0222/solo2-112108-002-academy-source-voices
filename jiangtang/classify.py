"""稿片切分与字句性质初判。

性质分五类：
- quote  逐字引用：必须有录文支撑，释义永远不能证明逐字引文；
- paraphrase 概述/现代重述：释义可以支撑白话讲解；
- question 反问：片内带反问标记的疑问 span；
- opponent 转述对手：替前人/问者概述的待反驳主张；
- narrator 讲解员串词：背景、指代说明等补充。

自动初判只给候选与置信度；quote 的确认、角色与性质改判以编辑判词为准。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 句末/分句标点，切分时保留在 span 文本内。
_SPLIT_RE = re.compile(r"[^，。？！；：、,.?!;:]+[，。？！；：、,.?!;:]?")

# 反问标记。
_QUESTION_MARKS = ("？", "?")
_RHETORICAL_HINTS = ("么", "吗", "岂", "何足", "怎能", "哪能", "难道")

# 转述对手（待反驳主张）的措辞。
_OPPONENT_HINTS = (
    "有人说", "有人把", "也有人", "别人说", "来人说", "来问的人",
    "门人问", "门人曰", "问者曰",
)

# 讲解员串词标记。
_NARRATOR_HINTS = (
    "另一条记载", "这里的", "说的是", "指的是", "意思是",
    "我们看", "这一句", "这一段",
)

# 现代重述/概述标记。
_PARAPHRASE_HINTS = (
    "可以引你", "不足以", "只算", "只认为", "办法", "这件事",
    "具体", "现代",
)

# 争议提示词：讲稿里承认两种讲法。
_DISPUTE_HINTS = ("两种意思", "两种理解", "也可以理解", "或指", "有争议")

# 强逐字引文门槛：归一化后与录文重合度。
_STRONG_QUOTE_RATIO = 0.80
_WEAK_QUOTE_RATIO = 0.45


def normalize(text):
    """去掉标点与空白后比较字面，引号本身不参与。"""
    return re.sub(r"[\s，。？！；：、,.?!;:'\"“”‘’（）()《》〈〉…—\-]", "", text)


def split_spans(text):
    """按标点把一段稿切成可判的字句 span，保留原文顺序。"""
    return [part.group(0) for part in _SPLIT_RE.finditer(text) if part.group(0).strip()]


@dataclass
class Span:
    fragment: str
    index: int
    text: str
    kind: str
    confidence: str
    speaker: str
    evidence: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def to_record(self):
        return {
            "fragment": self.fragment,
            "span": self.index,
            "text": self.text,
            "kind": self.kind,
            "confidence": self.confidence,
            "speaker": self.speaker,
            "evidence": list(self.evidence),
            "notes": list(self.notes),
        }


def _overlap_ratio(needle, haystack):
    """needle 的归一化字面在 haystack 中连续出现的比例。"""
    short = normalize(needle)
    long = normalize(haystack)
    if not short:
        return 0.0
    if short in long:
        return 1.0
    # 退一步：最长公共子串占比，处理录文中夹字的情况。
    best = 0
    grid = [0] * (len(long) + 1)
    for ch in short:
        previous = 0
        for col in range(1, len(long) + 1):
            cached = grid[col]
            if ch == long[col - 1]:
                grid[col] = previous + 1
                best = max(best, grid[col])
            else:
                grid[col] = 0
            previous = cached
    return best / len(short)


def _quote_candidates(library, fragment, span_text):
    """只在录文里找逐字候选；释义与校记不参与逐字证明。"""
    candidates = []
    for witness in library.witnesses:
        if witness["type"] != "录文":
            continue
        ratio = _overlap_ratio(span_text, witness["text"])
        if ratio >= _WEAK_QUOTE_RATIO:
            candidates.append((ratio, witness))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates


def _paraphrase_support(library, span_text):
    """释义只用于支撑白话讲解。"""
    support = []
    for witness in library.witnesses:
        if witness["type"] != "释义":
            continue
        ratio = _overlap_ratio(span_text, witness["text"])
        if ratio >= _WEAK_QUOTE_RATIO:
            support.append((ratio, witness))
    support.sort(key=lambda item: item[0], reverse=True)
    return support


def _base_kind(fragment, span_text):
    stripped = span_text.strip()
    if any(mark in stripped for mark in _QUESTION_MARKS) and any(
        hint in stripped for hint in _RHETORICAL_HINTS
    ):
        return "question", "auto"
    if any(hint in stripped for hint in _OPPONENT_HINTS):
        return "opponent", "auto"
    if any(hint in stripped for hint in _NARRATOR_HINTS):
        return "narrator", "auto"
    return "paraphrase", "auto"


def classify_fragment(library, fragment):
    """对一个稿片做自动初判，返回 Span 列表（未应用编辑判词）。"""
    spans = []
    voice = fragment["voice"]
    for index, span_text in enumerate(split_spans(fragment["text"])):
        kind, confidence = _base_kind(fragment, span_text)
        speaker = voice
        notes = []

        quote_candidates = _quote_candidates(library, fragment, span_text)
        if quote_candidates:
            best_ratio, best_witness = quote_candidates[0]
            if best_ratio >= _STRONG_QUOTE_RATIO and kind in {"paraphrase", "narrator"}:
                kind = "quote"
                confidence = "strong"
                speaker = best_witness["speaker"]
                notes.append("与录文字面高度重合，自动提为逐字候选，待编辑确认")
            elif kind != "quote":
                notes.append("与录文部分重合，仅作弱逐字候选，未达确认门槛")
        if kind == "quote":
            evidence = [
                {"key": library.cite_key(witness), "ratio": round(ratio, 2), "use": "录文"}
                for ratio, witness in quote_candidates
                if ratio >= _WEAK_QUOTE_RATIO
            ]
        else:
            support = _paraphrase_support(library, span_text)
            evidence = [
                {"key": library.cite_key(witness), "ratio": round(ratio, 2), "use": "释义"}
                for ratio, witness in support
            ]
            if support and kind == "paraphrase":
                confidence = "supported"

        if kind == "opponent":
            speaker = "问者/前人（转述对象）"
            notes.append("此句是替对手概述的待反驳主张，不应读成本人的教诲")
        if kind == "question":
            notes.append("反问句，须在同片或前片留有被反问的主张")
        if any(hint in span_text for hint in _DISPUTE_HINTS):
            notes.append("片内承认两种讲法，分歧须交编辑，不得并入同一古人之口")
        if kind == "paraphrase" and not evidence:
            notes.append("现代重述无逐字录文支撑，不得标为引文")

        spans.append(
            Span(
                fragment=fragment["id"],
                index=index,
                text=span_text,
                kind=kind,
                confidence=confidence,
                speaker=speaker,
                evidence=evidence,
                notes=notes,
            )
        )
    return spans


def classify_all(library):
    return {
        fragment["id"]: classify_fragment(library, fragment)
        for fragment in library.script
    }


def apply_judgments(library, workspace, auto=None):
    """把编辑判词覆盖到自动初判上，返回 fragment_id -> Span 列表。"""
    auto = auto or classify_all(library)
    judgments = library.load_annotations(workspace)
    result = {}
    for fragment_id, spans in auto.items():
        merged = []
        for span in spans:
            record = span.to_record()
            judgment = judgments.get((fragment_id, span.index))
            if judgment is not None:
                record["kind"] = judgment["kind"]
                record["speaker"] = judgment["speaker"]
                record["confidence"] = "adjudicated"
                record["notes"] = list(judgment.get("notes", ())) + [
                    f"编辑判词 {judgment['id']}（稿本 {judgment['revision']}）"
                ]
                if judgment.get("evidence"):
                    record["evidence"] = judgment["evidence"]
            record["index"] = record.pop("span")
            merged.append(Span(**record))
        result[fragment_id] = merged
    return result


def validate_judgment(library, workspace, fragment_id, span_index, kind, speaker, evidence):
    """落判词前的硬规则：quote 必须由录文支撑，释义不得证明逐字。"""
    fragment = library.fragment_by_id.get(fragment_id)
    if fragment is None:
        raise ValueError(f"稿片 {fragment_id} 不存在")
    spans = split_spans(fragment["text"])
    if not 0 <= span_index < len(spans):
        raise ValueError(f"稿片 {fragment_id} 没有第 {span_index} 个字句")
    if kind not in {"quote", "paraphrase", "question", "opponent", "narrator"}:
        raise ValueError(f"未知字句性质 {kind}")
    if kind == "quote":
        keys = [item["key"] for item in evidence] if evidence else []
        if not keys:
            raise ValueError("逐字引文必须回点至少一条录文出处")
        for key in keys:
            witness_id = key.split("@", 1)[0]
            witness = library.witness_by_id.get(witness_id)
            if witness is None:
                raise ValueError(f"出处 {key} 不存在")
            if witness["type"] != "录文":
                raise ValueError(
                    f"出处 {key} 是{witness['type']}，释义不能证明逐字引文"
                )
    for item in evidence or []:
        witness_id = item["key"].split("@", 1)[0]
        if witness_id not in library.witness_by_id:
            raise ValueError(f"出处 {item['key']} 不存在")
    return spans[span_index]
