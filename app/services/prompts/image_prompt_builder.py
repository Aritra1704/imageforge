from __future__ import annotations

import re
from typing import Any, Mapping

from app.schemas import PromptBundle


WORKFLOW_TYPE_DESCRIPTORS = {
    "ecard_background": "background asset workflow",
    "ecard_spot_illustration_v1": "ecard spot illustration workflow",
    "ecard_soft_background_v1": "ecard soft background workflow",
    "ecard_border_frame": "border frame asset workflow",
    "festival_motif_pack": "motif asset workflow",
    "hero_illustration": "hero illustration workflow",
    "supporting_scene": "supporting scene workflow",
    "bw_sketch_asset": "sketch asset workflow",
}

ASSET_TYPE_DESCRIPTORS = {
    "background_full": "full-bleed background illustration asset",
    "border_frame": "ornamental border frame asset",
    "hero_illustration": "hero illustration asset",
    "corner_decoration": "corner decoration asset",
    "object_pack": "isolated object illustration asset",
    "festival_motif": "festival motif illustration asset",
}

STYLE_PROFILE_DESCRIPTORS = {
    "draft_sketch": "draft sketch treatment",
    "bw_line_art": "black and white line art treatment",
    "flat_illustration": "flat illustration treatment",
    "soft_color_illustration": "soft color illustration treatment",
    "premium_render": "premium render treatment",
}

ASSET_ROLE_DESCRIPTORS = {
    "spot_illustration": [
        "spot illustration asset for card composition",
        "single focal subject",
        "clear negative space for card copy",
        "not full bleed",
    ],
    "background": [
        "soft atmospheric background asset",
        "subtle low-detail backdrop",
        "large open space for overlay text",
    ],
    "motif": [
        "small decorative motif asset",
        "isolated ornament",
        "designed to layer into a larger composition",
    ],
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

NEGATIVE_PROMPT_TERMS = (
    "text",
    "readable text",
    "lettering",
    "typography",
    "watermark",
    "logo",
    "clutter",
    "messy composition",
    "low quality",
    "blurry",
    "collage",
    "poster",
    "greeting card",
    "border",
    "frame",
    "multiple objects",
    "object grid",
    "decorative layout",
    "infographic",
    "page design",
    "full card design",
    "full bleed poster",
    "headline area",
)

ISOLATED_SUBJECT_ASSET_TYPES = {
    "hero_illustration",
    "object_pack",
}

NEGATIVE_PROMPT_EXCEPTIONS = {
    "border_frame": {"border", "frame"},
}

ASSET_MODE_DESCRIPTORS = {
    "background_full": [
        "clean background illustration",
        "plain or very soft background",
        "no embedded text",
    ],
    "border_frame": [
        "ornamental frame illustration",
        "empty interior",
        "no embedded text",
    ],
    "hero_illustration": [
        "single subject illustration",
        "centered composition",
        "isolated main subject",
        "plain or very soft background",
        "large margin around subject",
    ],
    "corner_decoration": [
        "small decorative corner asset",
        "isolated ornament",
        "plain or very soft background",
    ],
    "object_pack": [
        "single subject illustration",
        "centered composition",
        "isolated main subject",
        "plain or very soft background",
        "large margin around subject",
        "no collage",
    ],
    "festival_motif": [
        "single festive motif illustration",
        "isolated decorative subject",
        "centered composition",
        "plain or very soft background",
    ],
}


def _negative_prompt(asset_type: str, creative_direction: Any) -> str:
    blocked_terms = [
        term
        for term in NEGATIVE_PROMPT_TERMS
        if term not in NEGATIVE_PROMPT_EXCEPTIONS.get(asset_type, set())
    ]
    blocked_terms.extend(_creative_avoid_keywords(creative_direction))
    return ", ".join(dict.fromkeys(blocked_terms))


def _workflow_fragment(workflow_type: str) -> str | None:
    cleaned = _clean_text(workflow_type)
    if not cleaned:
        return None
    return WORKFLOW_TYPE_DESCRIPTORS.get(cleaned, f"{cleaned.replace('_', ' ')} workflow")


def _theme_fragments(theme_name: str, theme_bucket: str) -> list[str]:
    fragments = [f"inspired by {theme_name}"]
    cleaned_bucket = _clean_text(theme_bucket)
    if cleaned_bucket:
        fragments.append(f"{cleaned_bucket} theme context")
    return fragments


def _creative_direction_fragments(creative_direction: Any) -> list[str]:
    if not creative_direction:
        return []
    if not isinstance(creative_direction, Mapping):
        cleaned = _clean_text(creative_direction)
        return [cleaned] if cleaned else []

    fragments: list[str] = []
    motif_hint = _clean_text(creative_direction.get("motif_hint"))
    subject_hint = _clean_text(creative_direction.get("subject_hint"))
    if motif_hint:
        fragments.append(motif_hint)
    if subject_hint:
        fragments.append(subject_hint)

    visual_keywords = creative_direction.get("visual_keywords")
    if isinstance(visual_keywords, list):
        fragments.extend(
            keyword for keyword in (_clean_text(item) for item in visual_keywords) if keyword
        )

    extras = {
        key: value
        for key, value in creative_direction.items()
        if key not in {"motif_hint", "subject_hint", "visual_keywords", "avoid_keywords"}
    }
    fragments.extend(_mapping_fragments(extras))
    return fragments


def _creative_avoid_keywords(creative_direction: Any) -> list[str]:
    if not isinstance(creative_direction, Mapping):
        return []
    avoid_keywords = creative_direction.get("avoid_keywords")
    if not isinstance(avoid_keywords, list):
        return []
    return [keyword for keyword in (_clean_text(item) for item in avoid_keywords) if keyword]


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


def _scene_spec_fragments(scene_spec: Any, *, asset_type: str) -> list[str]:
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
        if asset_type not in ISOLATED_SUBJECT_ASSET_TYPES:
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


def _asset_role(value: Any, *, asset_type: str) -> str:
    cleaned = _clean_text(value)
    if cleaned:
        return cleaned
    if asset_type == "background_full":
        return "background"
    if asset_type == "festival_motif":
        return "motif"
    return "spot_illustration"


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
        workflow_type = _clean_text(payload.get("workflow_type")) or ""
        asset_type = str(payload["asset_type"]).strip()
        asset_role = _asset_role(payload.get("asset_role"), asset_type=asset_type)
        style_profile = str(payload["style_profile"]).strip()
        scene_spec = payload.get("scene_spec")
        render_spec = payload.get("render_spec")
        creative_direction = payload.get("creative_direction")
        tone_style = _clean_text(payload.get("tone_style")) or ""
        visual_style = _clean_text(payload.get("visual_style")) or ""
        selected_text = _clean_text(payload.get("selected_text")) or ""
        parts = [
            "simple reusable illustration asset",
            _workflow_fragment(workflow_type),
            STYLE_PROFILE_DESCRIPTORS.get(style_profile, style_profile),
            ASSET_TYPE_DESCRIPTORS.get(asset_type, asset_type),
            *ASSET_ROLE_DESCRIPTORS.get(asset_role, []),
            *ASSET_MODE_DESCRIPTORS.get(asset_type, []),
            *_theme_fragments(theme_name, theme_bucket),
        ]
        if cultural_context:
            parts.append(f"culturally respectful {cultural_context} details")
        if tone_style:
            parts.append(f"{tone_style} tone")
        if visual_style:
            parts.append(f"{visual_style} visual style")
        parts.extend(_creative_direction_fragments(creative_direction))
        parts.extend(_scene_spec_fragments(scene_spec, asset_type=asset_type))
        parts.extend(_render_spec_fragments(render_spec))

        message_hint = _extract_message_hint(selected_text)
        if message_hint:
            parts.append(f"thematic cues from {message_hint}")

        positive_prompt = ", ".join(
            dict.fromkeys(part for part in parts if isinstance(part, str) and part)
        )
        return PromptBundle(
            positive_prompt=positive_prompt,
            negative_prompt=_negative_prompt(asset_type, creative_direction),
        )
