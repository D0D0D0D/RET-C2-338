"""RET-C2-338 — domain constants.

APPI 2026 mandatory AI-recommendation disclosure. This text is **non-configurable**
(compliance-by-construction): it is appended by `appi_disclosure` and its presence is
verified fail-closed by `PostProcessNode._extra_security_gate_output()` (S-3 / S-5).
It must NOT be overridable via config — citizens may set brand voice (`system_prompt`)
but never disable or alter the disclosure.
"""

from __future__ import annotations

# Stable sentinel used by the S-3 presence gate. Changing this string is a
# compliance-relevant change and must be reviewed against the APPI 2026 outcome.
APPI_DISCLOSURE_MARKER = "【AI提案・APPI2026】"

# Customer-facing disclosure body. The marker is embedded verbatim so the gate
# can detect presence regardless of surrounding brand-voice formatting.
APPI_DISCLOSURE_TEXT = (
    f"{APPI_DISCLOSURE_MARKER} 本オファー文面およびおすすめは AI により自動生成されています"
    "（個人情報保護法2026 AIレコメンド開示）。内容は予告なく変更される場合があります。"
)
