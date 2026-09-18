# Stage 06 language normalization data

Owner: Agent A. Runtime: Ryzen AI 9 laptop only.

`normalization-golden.json` is a repository-owned engineering golden set for
the Stage 06 conversion boundary. Every row includes Hanji, 臺羅, the
MMS-facing POJ form, a Chinese gloss, and an example. It contains no student
data, textbook photograph, model weight, or external corpus dump.

`verified` means the entry is an approved deterministic mapping in this demo
set; it is not a claim that this repository replaces an official dictionary or
language specialist. `manual-review.json` records ambiguous/OOV/conflict cases
and the critical demo sentence that still requires the Agent B Stage 07 human
listening check.

The environment has no Taibun, THOKIT, or 臺灣言語工具 runtime package. Stage 06
therefore uses the documented offline fallback: a bounded reviewed lexicon and
versioned conversion rules. The converter never invents a pronunciation for an
OOV Hanji string.

The MMS boundary was checked against the official
[`facebook/mms-tts-nan`](https://huggingface.co/facebook/mms-tts-nan) model card
and its `vocab.json` revision `135c086`. The vocabulary is lower-case and does
not contain the superscript nasal `ⁿ`, so the model-facing `poj_citation` uses
`nn`. This repository does not download or execute the CC-BY-NC-4.0 model in
Stage 06; Agent B Stage 07 owns model-revision, license, synthesis, and human
audio validation.
