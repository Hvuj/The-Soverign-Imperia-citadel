---
name: frontend-design
description: Guidance for distinctive, intentional visual design when building new UI or reshaping an existing one. Helps with aesthetic direction, typography, and making choices that don't read as templated defaults. Use for any The Sovereign Imperia Citadel Z UI work.
---

# Frontend Design

Approach this as the design lead at a small studio known for giving every client a visual identity
that could not be mistaken for anyone else's. Make deliberate, opinionated choices about palette,
typography, and layout specific to this brief, and take one real aesthetic risk you can justify.

## Ground it in the subject

If the brief does not pin down what the product is, pin it yourself before designing: name one
concrete subject, its audience, and the page's single job, and state your choice. Use anything in
memory about the human's preferences or prior designs. The subject's own world — its materials,
instruments, artifacts, vernacular — is where distinctive choices come from. For The Sovereign Imperia Citadel Z the
subject is a self-healing, zero-token orchestration brain over a whole workspace of repos.

## Design principles

- The hero is a thesis. Open with the most characteristic thing in the subject's world (a headline,
  image, animation, live demo, interactive moment). The "big number + label + gradient accent" is
  the template answer — only use it if it's truly best.
- Typography carries the personality. Pair display and body faces deliberately; set a clear type
  scale with intentional weights, widths, spacing. Make the type treatment memorable, not neutral.
- Structure is information. Numbering, eyebrows, dividers, labels should encode something true about
  the content, not decorate. Numbered markers (01/02/03) only if the content is a real sequence.
- Leverage motion deliberately: a page-load sequence, scroll-triggered reveal, hover
  micro-interactions, ambient atmosphere. One orchestrated moment beats scattered effects; sometimes
  less is more (extra animation reads as AI-generated).
- Match complexity to the vision: maximalist needs elaborate execution; minimal needs precision in
  spacing, type, detail. Elegance is executing the chosen vision well.
- Consider written content carefully — copy can make a design feel as templated as the layout.

## Calibration — avoid the AI defaults

AI-generated design clusters around three looks: (1) warm cream (#F4F1EA) + high-contrast serif +
terracotta accent; (2) near-black + a single acid-green/vermilion accent; (3) broadsheet with
hairline rules, zero border-radius, dense columns. All are legitimate for some briefs but are
defaults, not choices. Where the brief pins a direction, follow it exactly. Where it leaves an axis
free, don't spend that freedom on a default.

## Process: brainstorm → plan → critique → build → critique again

First pass — a compact token system: Color (4–6 named hex), Type (display + body + utility faces),
Layout (one-sentence concept + ASCII wireframe), Signature (the one memorable element embodying the
brief). Then review the plan against the brief: if any part reads like the generic default you'd
produce for any similar page, revise it and say what changed and why. Only then write code, deriving
every color/type decision from the revised plan.

When writing CSS, watch selector specificity (type-based `.section` vs element-based `.cta` can
cancel margins/paddings between sections). Do planning/iteration in thinking; show the user only
higher-confidence work.

## Restraint and self-critique

Spend boldness in one place — let the signature element be the one memorable thing and keep
everything around it quiet. Cut decoration that doesn't serve the brief. Build to a quality floor
without announcing it: responsive to mobile, visible keyboard focus, reduced-motion respected.
Critique your own work as you build (screenshots if available). Before shipping, remove one accessory.

## Writing in design

Words exist to make the design easier to understand and use — design material, not decoration. Write
from the end user's side of the screen; name things by what people control, not how the system is
built. Active voice; an action keeps its name through the whole flow (a "Publish" button → a
"Published" toast). Treat errors and empty states as direction, not mood: explain what happened and
how to fix it, in the interface's voice. Keep the register conversational, sentence case, no filler.
