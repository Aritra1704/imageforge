# Role
Image asset generator using ComfyUI.

## Responsibilities
- Generate illustration-first image assets
- Provide multiple candidates
- Rank and return recommendation metadata

## Rules
- NO TEXT inside images
- output must be clean assets
- optimized for composition
- primary eCard role is `spot_illustration`; soft background is secondary/opt-in

## Problems
- slow generation
- unclear candidate visibility

## Output
- multiple image options for selection
- include `quality_score`, `relevance_score`, `reason_codes`, and `recommended_candidate_id`
