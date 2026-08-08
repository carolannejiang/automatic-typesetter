# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Project contracts

Invariants that span files and won't be obvious from any single one.

### Chapter numbering (models.Chapter.numbered / .number)

- `numbered=False` marks front/back matter (Introduction, Conclusion,
  References, Appendix). `number` holds an author-typed figure ("I", "2");
  `None` means number by position. Both are set by `ingest.classify_chapters`
  at the end of `ingest()`: typed `I. `/`1. ` title figures that count 1..k
  in document order (at least two — one is too weak a signal) become display
  numbers, stripped from the titles; otherwise standard furniture titles
  fall back unnumbered.
- A chapter's number is its position **among numbered chapters only** —
  never its index in `book.chapters`. Every writer counts with a `seq` that
  unnumbered chapters don't advance (printbook, epub, latex, indesign).
  Keep that pattern in new writers and in anything iterating chapters.
- Print and epub writers emit `class="chapter unnumbered"` on matter, and
  theme CSS keys off it: the shared DROP_CAP rule, polimi's lettrine and
  its counter spine (`counter-increment: chapter`), and section-number
  suppression. If a writer stops emitting the class, or a theme adds
  chapter-scoped counters/decoration without excluding `.unnumbered`,
  numbering silently goes wrong. The LaTeX equivalents: `\chapter*` +
  `\addcontentsline`, secnumdepth saved/restored around the chapter, and
  lettrine openers skipped.
- The global `chapter_numbers` option only suppresses display; it does not
  change classification, and matter dress rules (no drop cap/lettrine) key
  on `chapter.numbered` alone.
- Theme `chapter_label(number)` implementations must interpolate the number
  (str or int), not do arithmetic on it — typed figures arrive as strings.
