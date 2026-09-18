from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..models import SCHEMA_VERSION, Utterance, UtteranceSegment


NORMALIZER_VERSION = "hol-language-normalizer-v1"
GOLDEN_LEXICON_VERSION = "hol-curated-golden-v1"
RULESET_VERSION = "tailo-to-mms-poj-v1"
MMS_POJ_PROFILE_VERSION = "facebook-mms-tts-nan-vocab@135c086"

# The official facebook/mms-tts-nan vocab contains these lower-case letters,
# POJ tone letters/combining marks, space, apostrophe, and hyphen. The API emits
# the model-facing citation in this conservative subset so Agent B can pass the
# value directly to the tokenizer without forwarding Hanji or unsupported text.
_MMS_LETTERS = set("abceghijklmnopstu")
_MMS_PRECOMPOSED = set("àáâèéêìíîòóôùúûāēīńōūǹḿ")
_MMS_COMBINING = {"\u0302", "\u0304", "\u030d", "\u0358"}
_MMS_SEPARATORS = {" ", "-", "'"}
_STRIPPED_PUNCTUATION = str.maketrans({
    char: " " for char in ".,!?;:，。！？；：、()（）[]【】{}「」『』…"
})

PronunciationStatus = Literal["verified", "converted", "needs_review"]


@dataclass(frozen=True, slots=True)
class NormalizationStep:
    name: str
    tool_version: str
    input: dict[str, Any]
    output: dict[str, Any]


@dataclass(frozen=True, slots=True)
class NormalizationAudit:
    pipeline_version: str
    steps: tuple[NormalizationStep, ...]
    needs_review_reasons: tuple[str, ...]
    tailo_candidates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    utterance: Utterance
    audit: NormalizationAudit


@dataclass(frozen=True, slots=True)
class GoldenEntry:
    entry_id: str
    hanji: str
    tailo: str
    poj: str
    zh_gloss: str
    example: str
    status: PronunciationStatus
    review_reasons: tuple[str, ...]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def _replace_syllable_initials(value: str) -> str:
    value = re.sub(r"(?i)(?<![a-z])tsh", lambda match: "chh" if match.group().islower() else "Chh", value)
    return re.sub(r"(?i)(?<![a-z])ts", lambda match: "ch" if match.group().islower() else "Ch", value)


def _replace_ing(value: str) -> str:
    mapping = {
        "ing": "eng",
        "īng": "ēng",
        "íng": "éng",
        "ìng": "èng",
        "îng": "êng",
        "i̍ng": "e̍ng",
    }
    for source, target in mapping.items():
        value = value.replace(source, target)
    return value


def _mms_unknown_characters(value: str) -> tuple[str, ...]:
    unknown: list[str] = []
    for char in value:
        if (
            char in _MMS_LETTERS
            or char in _MMS_PRECOMPOSED
            or char in _MMS_COMBINING
            or char in _MMS_SEPARATORS
        ):
            continue
        unknown.append(char)
    return tuple(dict.fromkeys(unknown))


def tailo_to_mms_poj(tailo: str) -> tuple[str | None, tuple[str, ...]]:
    """Convert a bounded 臺羅 subset into the MMS Min Nan tokenizer profile.

    This is deliberately not a free-form romanization generator. It converts
    only supplied/curated 臺羅, changes the documented orthographic differences
    needed by the checked-in golden set, and refuses characters outside the
    official model vocabulary. Superscript nasal ``ⁿ`` is serialized as ``nn``
    because ``ⁿ`` is absent from the model vocab while ``n`` is present.
    """

    value = _normalize_text(tailo).lower().translate(_STRIPPED_PUNCTUATION)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.replace("ⁿ", "nn")
    for source, target in {"uí": "úi", "uì": "ùi", "uî": "ûi", "uī": "ūi"}.items():
        value = value.replace(source, target)
    value = _replace_syllable_initials(value)
    value = value.replace("oo", "o\u0358")
    value = _replace_ing(value)
    # 臺羅 ua/ue correspond to POJ oa/oe. Match only a following vowel so
    # standalone u and diphthongs such as ui remain unchanged.
    value = re.sub(r"u(?=[aāáàâeēéèê])", "o", value)
    unknown = _mms_unknown_characters(value)
    return (None, unknown) if unknown else (value, ())


class LanguageNormalizer:
    def __init__(self, golden_path: Path) -> None:
        self.golden_path = golden_path.resolve()
        self.entries = self._load_entries(self.golden_path)
        self.by_hanji: dict[str, list[GoldenEntry]] = {}
        for entry in self.entries:
            self.by_hanji.setdefault(_normalize_text(entry.hanji), []).append(entry)

    @staticmethod
    def _load_entries(path: Path) -> tuple[GoldenEntry, ...]:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot load language golden set: {path}") from exc
        if document.get("schema_version") != "language-golden.v1":
            raise ValueError("unsupported language golden set version")
        entries: list[GoldenEntry] = []
        for item in document.get("entries", []):
            required = ("id", "hanji", "tailo", "poj", "zh_gloss", "example", "status")
            if any(not str(item.get(key, "")).strip() for key in required):
                raise ValueError(f"golden entry is incomplete: {item.get('id', '<unknown>')}")
            status = str(item["status"])
            if status not in {"verified", "needs_review"}:
                raise ValueError(f"invalid golden status: {status}")
            entry = GoldenEntry(
                entry_id=str(item["id"]),
                hanji=_normalize_text(str(item["hanji"])),
                tailo=_normalize_text(str(item["tailo"])),
                poj=_normalize_text(str(item["poj"])),
                zh_gloss=_normalize_text(str(item["zh_gloss"])),
                example=_normalize_text(str(item["example"])),
                status=status,  # type: ignore[arg-type]
                review_reasons=tuple(str(reason) for reason in item.get("review_reasons", [])),
            )
            converted, unknown = tailo_to_mms_poj(entry.tailo)
            if converted != entry.poj or unknown:
                raise ValueError(f"golden POJ mismatch for {entry.entry_id}")
            entries.append(entry)
        if len(entries) < 30:
            raise ValueError("language golden set must contain at least 30 entries")
        return tuple(entries)

    def normalize(
        self,
        *,
        text: str,
        lang: Literal["nan-TW", "zh-TW"],
        tailo_citation: str | None = None,
    ) -> NormalizationResult:
        normalized_text = _normalize_text(text)
        if not normalized_text:
            raise ValueError("text must contain a non-whitespace character")
        steps: list[NormalizationStep] = [
            NormalizationStep(
                name="unicode_normalization",
                tool_version=f"python-unicodedata-{unicodedata.unidata_version}",
                input={"text": text},
                output={"text": normalized_text},
            )
        ]
        digest = hashlib.sha256(
            f"{lang}\0{normalized_text}\0{tailo_citation or ''}".encode("utf-8")
        ).hexdigest()[:20]

        if lang == "zh-TW":
            utterance = Utterance(
                schema_version=SCHEMA_VERSION,
                id=f"utt_{digest}",
                segments=[UtteranceSegment(
                    lang=lang,
                    hanji=normalized_text,
                    tailo_citation=None,
                    poj_citation=None,
                    zh_gloss=None,
                    source="generated",
                    pronunciation_status="verified",
                )],
                tts_provider="windows",
            )
            return NormalizationResult(
                utterance,
                NormalizationAudit(NORMALIZER_VERSION, tuple(steps), (), ()),
            )

        matches = self.by_hanji.get(normalized_text, [])
        candidates = tuple(dict.fromkeys(entry.tailo for entry in matches))
        steps.append(NormalizationStep(
            name="hanji_to_tailo_candidates",
            tool_version=GOLDEN_LEXICON_VERSION,
            input={"hanji": normalized_text},
            output={"candidates": list(candidates)},
        ))

        review_reasons: list[str] = []
        chosen_tailo: str | None
        zh_gloss: str | None = matches[0].zh_gloss if matches else None
        source: Literal["textbook", "dictionary", "generated"]
        status: PronunciationStatus

        if tailo_citation is not None:
            chosen_tailo = _normalize_text(tailo_citation)
            if not chosen_tailo:
                raise ValueError("tailo_citation must be null or contain a non-whitespace character")
            source = "textbook"
            status = "converted"
            if candidates and chosen_tailo not in candidates:
                review_reasons.append("textbook_dictionary_conflict")
        elif not matches:
            chosen_tailo = None
            source = "generated"
            status = "needs_review"
            review_reasons.append("oov")
        else:
            chosen_tailo = matches[0].tailo
            source = "dictionary"
            status = "verified"
            if len(candidates) > 1:
                review_reasons.append("multiple_pronunciations")
            for entry in matches:
                review_reasons.extend(entry.review_reasons)

        poj: str | None = None
        if chosen_tailo is not None:
            converted, unknown = tailo_to_mms_poj(chosen_tailo)
            steps.append(NormalizationStep(
                name="tailo_to_poj",
                tool_version=RULESET_VERSION,
                input={"tailo": chosen_tailo},
                output={"poj": converted, "unknown_characters": list(unknown)},
            ))
            if unknown:
                review_reasons.append("unsupported_mms_character")
            poj = converted

        review_reasons = list(dict.fromkeys(review_reasons))
        if review_reasons:
            status = "needs_review"
            # needs_review text must never be sent directly to MMS-TTS.
            poj = None

        steps.append(NormalizationStep(
            name="mms_vocabulary_gate",
            tool_version=MMS_POJ_PROFILE_VERSION,
            input={"poj": poj},
            output={"accepted": poj is not None and not review_reasons},
        ))
        utterance = Utterance(
            schema_version=SCHEMA_VERSION,
            id=f"utt_{digest}",
            segments=[UtteranceSegment(
                lang=lang,
                hanji=normalized_text,
                tailo_citation=chosen_tailo,
                poj_citation=poj,
                zh_gloss=zh_gloss,
                source=source,
                pronunciation_status=status,
            )],
            tts_provider="mms-tts-nan" if poj is not None and status != "needs_review" else None,
        )
        return NormalizationResult(
            utterance,
            NormalizationAudit(
                NORMALIZER_VERSION,
                tuple(steps),
                tuple(review_reasons),
                candidates,
            ),
        )
