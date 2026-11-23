"""Console stylesheet: the only place the operator console's look lives.

``mount_console`` hands this string to ``mount_gradio_app(css=...)``; Gradio 6
no longer takes ``css`` on the ``Blocks`` constructor. Colours come from
Gradio's own CSS variables so the console follows the light and dark themes;
the origin badges are the single exception, and their backgrounds are
translucent so the literal accent stays readable on either theme.
"""

CONSOLE_CSS = """
/* ── voice counter ─────────────────────────────────────────────────── */
.vf-count {
  margin: 0 0 12px;
  font-size: 0.85rem;
  color: var(--body-text-color-subdued);
}

/* ── cards ─────────────────────────────────────────────────────────── */
.vf-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.vf-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  border: 1px solid var(--border-color-primary);
  border-radius: 14px;
  background: var(--background-fill-secondary);
  color: var(--body-text-color);
  transition: box-shadow 0.15s ease, transform 0.15s ease, border-color 0.15s ease;
}

.vf-card:hover {
  border-color: var(--border-color-accent, var(--border-color-primary));
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.14);
  transform: translateY(-1px);
}

.vf-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.vf-name {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  line-height: 1.3;
  color: var(--body-text-color);
}

.vf-slug,
.vf-slug code,
.vf-lineage code,
.vf-recipe code {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 0.8rem;
  color: var(--body-text-color-subdued);
}

.vf-slug {
  display: block;
  margin: 0;
  color: var(--body-text-color-subdued);
}

/* ── badges ─────────────────────────────────────────────────────────── */
.vf-badge {
  flex: none;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  line-height: 1.5;
  white-space: nowrap;
}

.vf-badge-designed {
  background: rgba(139, 92, 246, 0.16);
  color: #8b5cf6;
}

.vf-badge-imported {
  background: rgba(16, 163, 127, 0.16);
  color: #10a37f;
}

.vf-badge-derived {
  background: rgba(224, 145, 10, 0.18);
  color: #c47f06;
}

/* ── chips ──────────────────────────────────────────────────────────── */
.vf-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.vf-chip {
  padding: 1px 8px;
  border: 1px solid var(--border-color-primary);
  border-radius: 999px;
  font-size: 0.75rem;
  line-height: 1.5;
  color: var(--body-text-color-subdued);
  background: transparent;
  white-space: nowrap;
}

.vf-chip-warn {
  border-color: rgba(224, 145, 10, 0.5);
  background: rgba(224, 145, 10, 0.12);
  color: #b45309;
}

.vf-tag {
  border-style: dashed;
}

/* ── card body ──────────────────────────────────────────────────────── */
.vf-recipe,
.vf-transcript,
.vf-lineage {
  margin: 0;
  font-size: 0.8rem;
  line-height: 1.45;
  color: var(--body-text-color-subdued);
}

.vf-recipe,
.vf-transcript {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.vf-transcript {
  font-style: italic;
}

.vf-lineage code {
  padding: 0 4px;
  border-radius: 4px;
  background: var(--background-fill-primary);
}

.vf-empty {
  padding: 24px;
  text-align: center;
  color: var(--body-text-color-subdued);
}

/* ── preview slots (kept minimal: structure belongs to preview.py) ─── */
.vf-slots {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.vf-slot {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border: 1px solid var(--border-color-primary);
  border-radius: 12px;
  background: var(--background-fill-secondary);
}

.vf-slot-empty {
  color: var(--body-text-color-subdued);
  border-style: dashed;
}

.vf-slot-title {
  margin: 0;
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--body-text-color-subdued);
}

.vf-slot p {
  margin: 0;
  font-size: 0.85rem;
}

.vf-slot audio,
.vf-candidate audio {
  width: 100%;
}

/* ── design candidates ──────────────────────────────────────────────── */
.vf-candidates {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.vf-candidate {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border: 1px solid var(--border-color-primary);
  border-radius: 12px;
  background: var(--background-fill-secondary);
}

.vf-candidate-title,
.vf-candidate-recipe {
  margin: 0;
  font-size: 0.85rem;
}

.vf-candidate-recipe {
  color: var(--body-text-color-subdued);
}
"""
