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

WORKFLOW_TYPE_DESCRIPTORS = {
    "ecard_background": "background workflow asset for later composition",
    "ecard_border_frame": "border frame workflow asset for later composition",
    "festival_motif_pack": "festival motif pack workflow asset",
    "hero_illustration": "hero illustration workflow asset",
    "supporting_scene": "supporting scene workflow asset",
    "bw_sketch_asset": "black and white sketch workflow asset",
}

ASSET_TYPE_DESCRIPTORS = {
    "background_full": "full-bleed background asset",
    "border_frame": "ornamental border frame asset",
    "hero_illustration": "hero illustration asset",
    "corner_decoration": "corner decoration asset",
    "object_pack": "decorative object pack asset",
    "festival_motif": "festival motif asset",
}

STYLE_PROFILE_DESCRIPTORS = {
    "draft_sketch": "draft sketch treatment",
    "bw_line_art": "black and white line art treatment",
    "flat_illustration": "flat illustration treatment",
    "soft_color_illustration": "soft color illustration treatment",
    "premium_render": "premium render treatment",
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
    "text, readable text, lettering, typography, watermark, logo, clutter, "
    "messy composition, distorted typography, low quality, blurry"
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


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return str(value).strip() or None


def _mapping_fragments(
    spec: Mapping[str, Any], *, special_labels: dict[str, str] | None = None
) -> list[str]:
    fragments: list[str] = []
    special_labels = special_labels or {}
    for key, value in spec.items():
        if value is None:
            continue
        if isinstance(value, Mapping):
            nested = _mapping_fragments(value)
            if nested:
                fragments.extend(nested)
            continue
        if isinstance(value, list):
            cleaned_items = [_clean_text(item) for item in value]
            joined = ", ".join(item for item in cleaned_items if item)
            if joined:
                label = special_labels.get(key, key.replace("_", " "))
                fragments.append(f"{label}: {joined}")
            continue

        cleaned = _clean_text(value)
        if not cleaned:
            continue
        label = special_labels.get(key, key.replace("_", " "))
        if label:
            fragments.append(f"{label}: {cleaned}")
        else:
            fragments.append(cleaned)
    return fragments


def _scene_spec_fragments(scene_spec: Any) -> list[str]:
    if not scene_spec:
        return []
    if isinstance(scene_spec, str):
        cleaned = _clean_text(scene_spec)
        return [cleaned] if cleaned else []
    if isinstance(scene_spec, Mapping):
        fragments: list[str] = []
        subject = _clean_text(scene_spec.get("subject"))
        composition = _clean_text(scene_spec.get("composition"))
        background_intent = _clean_text(scene_spec.get("background_intent"))
        if subject:
            fragments.append(subject)
        if composition:
            fragments.append(f"{composition} composition")
        if background_intent:
            fragments.append(background_intent)

        extras = {
            key: value
            for key, value in scene_spec.items()
            if key not in {"subject", "composition", "background_intent"}
        }
        fragments.extend(_mapping_fragments(extras))
        return fragments
    cleaned = _clean_text(scene_spec)
    return [cleaned] if cleaned else []


def _render_spec_fragments(render_spec: Any) -> list[str]:
    if not render_spec:
        return []
    if isinstance(render_spec, str):
        cleaned = _clean_text(render_spec)
        return [cleaned] if cleaned else []
    if isinstance(render_spec, Mapping):
        fragments: list[str] = []
        width = render_spec.get("width")
        height = render_spec.get("height")
        if isinstance(width, int) and isinstance(height, int):
            fragments.append(f"{width}x{height}")

        orientation = _clean_text(render_spec.get("orientation"))
        quality_profile = _clean_text(render_spec.get("quality_profile"))
        if orientation:
            fragments.append(f"{orientation} orientation")
        if quality_profile:
            fragments.append(f"{quality_profile} quality profile")

        extras = {
            key: value
            for key, value in render_spec.items()
            if key not in {"width", "height", "orientation", "quality_profile"}
        }
        fragments.extend(_mapping_fragments(extras))
        return fragments
    cleaned = _clean_text(render_spec)
    return [cleaned] if cleaned else []


class ImagePromptBuilder:
    def build(self, payload: Mapping[str, Any]) -> PromptBundle:
        theme_name = str(payload["theme_name"]).strip()
        theme_bucket = str(payload["theme_bucket"]).strip()
        cultural_context = _clean_text(payload.get("cultural_context")) or ""
        workflow_type = str(payload["workflow_type"]).strip()
        asset_type = str(payload["asset_type"]).strip()
        style_profile = str(payload["style_profile"]).strip()
        scene_spec = payload.get("scene_spec")
        render_spec = payload.get("render_spec")
        tone_style = _clean_text(payload.get("tone_style")) or ""
        visual_style = _clean_text(payload.get("visual_style")) or ""
        selected_text = _clean_text(payload.get("selected_text")) or ""

        theme_key = theme_name.lower()
        motifs = THEME_MOTIFS.get(
            theme_key,
            f"tasteful {theme_bucket} symbolism inspired by {theme_name}",
        )

        parts = [
            "image-only visual asset",
            WORKFLOW_TYPE_DESCRIPTORS.get(workflow_type, workflow_type),
            ASSET_TYPE_DESCRIPTORS.get(asset_type, asset_type),
            STYLE_PROFILE_DESCRIPTORS.get(style_profile, style_profile),
            f"{theme_name} theme",
            motifs,
            "clean layered composition",
            "optimized for fast reusable asset generation",
            "intended for downstream composition",
        ]
        if cultural_context:
            parts.append(f"culturally respectful {cultural_context} details")
        if tone_style:
            parts.append(f"{tone_style} tone")
        if visual_style:
            parts.append(f"{visual_style} visual style")
        parts.extend(_scene_spec_fragments(scene_spec))
        parts.extend(_render_spec_fragments(render_spec))

        message_hint = _extract_message_hint(selected_text)
        if message_hint:
            parts.append(f"thematic cues from {message_hint}")

        positive_prompt = ", ".join(dict.fromkeys(parts))
        return PromptBundle(
            positive_prompt=positive_prompt,
            negative_prompt=NEGATIVE_PROMPT,
        )
