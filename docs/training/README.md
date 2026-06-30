# ESB Training Decks

Two trainer-led walkthrough presentations for the Equipment Status Board:

| Deck | Audience | Slides |
|------|----------|--------|
| [`members.md`](members.md) | Anyone who uses the space (no account) | 13 |
| [`technicians.md`](technicians.md) | Volunteer repair technicians | 17 |

Both are concise speaker decks — terse on-slide cues for a knowledgeable
presenter to expand on, with real ESB screenshots. They cover the web
interface, QR-code scanning, and Slack, plus the Wi-Fi/VPN network caveat.

For running an interactive hands-on demo instead of the slides, use the
matching checklists:

- [`member-demo-checklist.md`](member-demo-checklist.md)
- [`technician-demo-checklist.md`](technician-demo-checklist.md)

## Before you present

Fill in the one bracketed blank in each deck (flagged in a presenter
comment near the top of the file):

- the ESB web address posted in the space (on the dashboard slide)

## Rendering

The decks are [Marp](https://marp.app/) Markdown. Pre-rendered `members.pdf`
and `technicians.pdf` are checked in. To re-render after editing:

```bash
# PDF (needs a Chromium; set CHROME_PATH if not auto-detected)
npx @marp-team/marp-cli docs/training/members.md      --html --allow-local-files -o members.pdf
npx @marp-team/marp-cli docs/training/technicians.md  --html --allow-local-files -o technicians.pdf

# Editable PowerPoint / Google Slides import
npx @marp-team/marp-cli docs/training/members.md      --html --allow-local-files -o members.pptx

# Self-contained HTML
npx @marp-team/marp-cli docs/training/members.md      --html --allow-local-files -o members.html
```

`--html` is required (the slides use a little inline HTML/CSS for the status
chips, Slack mock cards, and the network-access callout box).

## Screenshots

Images come from `../images/` and are produced by the repo's existing
screenshot harness (`make screenshots` → `scripts/generate_screenshots.py`),
plus a few training-specific shots (login page, equipment registry,
create-repair form, anonymous status dashboard, report confirmation).
Re-run the harness after UI changes to refresh them.

> **Slack screenshots:** the deck represents Slack commands and bot replies as
> faithful styled mockups rather than live captures (a real Slack workspace
> can't be screenshotted headlessly). Demo the real commands live, or drop in
> captures from your workspace if you prefer.
