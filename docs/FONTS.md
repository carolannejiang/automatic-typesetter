# Fonts

The repository **bundles zero font files** — there are no `.ttf`/`.otf`/`.woff`/`.woff2`
anywhere in the source tree, and every `@font-face` rule uses `local()` only (never a
`url()` to embed a font). All fonts are resolved at render time from the operating system,
apt packages installed in the Docker image, or a TeX distribution.

## Auto-installed in Docker (via apt, `Dockerfile:10`)

These are the fallback families. They are installed for you in the container image but are
not part of the source tree:

- `fonts-dejavu-core`
- `fonts-liberation`
- `fonts-texgyre`
- `fonts-urw-base35`

For the CSS→PDF (WeasyPrint) path, these four packages are enough to render every theme
using its fallback faces.

## Commercial / OS fonts you must install yourself for exact fidelity

Each theme's font stack *prefers* these faces, then falls through to the apt fallbacks if
they are absent.

| Theme | Preferred fonts (require local install) |
|---|---|
| `themes/polimi.py` | **Minion Pro**, **Myriad Pro** |
| `themes/vsi.py` | **VSI Miller** (Miller Text), OUP Argo, Lithos Pro, Helvetica Neue |
| `themes/memoir.py` / `themes/memoir2.py` | **EB Garamond**, Garamond Premier Pro, Adobe Garamond Pro |
| `themes/tufte.py` | **Tufte Bembo** (Bembo / ETBembo), Gill Sans |
| `themes/mydiss.py` | **Fedra Serif B**, Charter / XCharter |
| `themes/base.py` (default) | Iowan Old Style, Palatino, Avenir Next |
| `themes/classical.py` | Source Serif Pro / Source Serif 4 |

The three `@font-face` blocks — VSI Miller (`themes/vsi.py:177`), Tufte Bembo
(`themes/tufte.py:171`), and Fedra Serif B (`themes/mydiss.py:92`) — are **all
`local()`-only**. They render only if that commercial font is already installed; otherwise
the stack falls through to the fallbacks.

## LaTeX export path (`latex.py`, needs a TeX distribution)

- **TeX Gyre** (Pagella / Schola / Termes) + DejaVu Sans Mono — general books
- TeX packages: **`ebgaramond`** (memoir), **`XCharter`** (mydiss)
- polimi uses `\IfFontExistsTF{Minion Pro}` / `{Myriad Pro}` / `{Monaco}`, falling back to
  TeX Gyre / DejaVu files if not installed

## InDesign path (`docs/INDESIGN.md:56`)

Defaults to **Minion Pro**, **Myriad Pro**, and **Courier New** — activated via InDesign's
"Missing Fonts" dialog from Adobe Fonts.

## Notes

- Nothing is downloaded or bundled by the repo.
- Installing the commercial faces above only matters if you want each theme's *first-choice*
  typeface rather than its fallback.
- The README confirms fonts are **not embedded** in the output PDF (system serif stacks are
  used).
