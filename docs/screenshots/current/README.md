# Current README product shots

Captured on 2026-10-23 from main snapshot `dc44c96` with the production frontend
build and Go server from that snapshot. The Android captures use the Roami
0.3.8 app on a Redmi Note 8, connected to the same isolated demo server.

| Asset | Actual view |
|---|---|
| `hero.<lang>.webp` | Desktop Home and Android Home |
| `projects.<lang>.webp` | Launchpad project, feature worktree, and terminal session |
| `capabilities.<lang>.webp` | Capability center, Skills tab |
| `workspace.<lang>.webp` | File workspace with the demo status module open |
| `android.<lang>.webp` | Android Home and Tools |

`en` and `zh` are separate captures of the English and Simplified Chinese UI.
Screens use public demo repositories and seeded conversation/task text, not a
live model evaluation. The sample state tests were executed in a disposable
session; the screenshots are not a claim that a coding agent performed that run.

Desktop capture uses `roami chrome`; Android images come from the device's
`adb exec-out screencap -p`, preserving the native app and system bars. Device
frames come from the product-shots skill's `mockup.py`. Final files are WebP,
1600 pixels wide, under the repository's 1 MiB binary limit.

The development server, data, and tmux socket were isolated with
`scripts/dev/isolated-roami.sh`. No production session or project was modified.
The original product shots in the parent folder remain historical references.
