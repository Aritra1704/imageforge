from __future__ import annotations

import re
from typing import Any, Mapping

from app.schemas import PromptBundle


THEME_MOTIFS = {
    "ugadi": "festive South Indian decor, mango leaves toran, rangoli accents, diya glow",
    "ramadan": "crescent moon, lantern glow, deep navy and gold palette, serene evening ambiance",
    "birthday": "pastel balloons, premium stationery texture, confetti accents, celebratory elegance",
    "diwali": "warm diya light, marigold details, rangoli flourishes, rich festive glow",
    "christmas": "soft evergreen details, warm lights, tasteful ornaments, seasonal calm",
    "new year": "clean celebratory sparkle, refined fireworks glow, premium festive backdrop",
}

STOP_WORDS = {
    "happy",
    "wishing",
    "wish",
    "with",
    "your",
    "yours",
    "this",
    "that",
    "have",
    "from",
    "you",
    "joy",
    "love",
    "peace",
    "prosperity",
    "greetings",
    "greeting",
}

NEGATIVE_PROMPT = (
    "text, watermark, logo, clutter, messy composition, distorted typography, "
    "low quality, blurry"
)


def _extract_message_hint(selected_text: str) -> str | None:
    words = re.findall(r"[A-Za-z']+", selected_text.lower())
    filtered: list[str] = []
    for word in words:
        if len(word) < 4 or word in STOP_WORDS:
            continue
        if word not in filtered:
            filtered.append(word)
        if len(filtered) == 5:
            break
    if not filtered:
        return None
    return "subtle cues of " + " ".join(filtered)


class ImagePromptBuilder:
    def build(self, payload: Mapping[str, Any]) -> PromptBundle:
        theme_name = str(payload["theme_name"]).strip()
        theme_bucket = str(payload["theme_bucket"]).strip()
        cultural_context = (payload.get("cultural_context") or "").strip()
        tone_style = (payload.get("tone_style") or "balanced").strip()
        visual_style = (payload.get("visual_style") or "refined").strip()
        selected_text = str(payload["selected_text"]).strip()

        theme_key = theme_name.lower()
        motifs = THEME_MOTIFS.get(
            theme_key,
            f"tasteful {theme_bucket} symbolism inspired by {theme_name}",
        )

        parts = [
            "greeting card background",
            "portrait card layout",
            "premium stationery aesthetic",
            f"{visual_style} visual style",
            f"{tone_style} tone",
            f"{theme_name} theme",
            motifs,
            "clear central text area",
            "balanced margins",
            "clean layered composition",
        ]
        if cultural_context:
            parts.append(f"culturally respectful {cultural_context} details")

        message_hint = _extract_message_hint(selected_text)
        if message_hint:
            parts.append(message_hint)

        positive_prompt = ", ".join(dict.fromkeys(parts))
        return PromptBundle(
            positive_prompt=positive_prompt,
            negative_prompt=NEGATIVE_PROMPT,
        )
