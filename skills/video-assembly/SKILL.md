---
name: video-assembly
description: Create timestamped frame previews for visual review, then concatenate chosen complete MP4 clips with a matching timeline manifest. Use for inspecting supplied clips and assembling selected footage; previews do not establish semantic matches.
---

Use available visual evidence or suitable analysis to select clips. Filenames and media metadata alone do not establish scene meaning. Keep uncertainty explicit when the available capabilities cannot confirm a match.

For temporal inspection, create a workspace spec:

```json
{"input":{"path":"clips/intro.mp4"},"image":"work/intro-frames.png","manifest":"work/intro-frames.json","fractions":[0,0.25,0.5,0.75,1]}
```

Run `python /path/from/skill-read/scripts/clip_inspection.py --workspace /your/workspace --spec inspection.json`. Inspection requires prepared Pillow >=10.1, `ffmpeg` and `ffprobe`. It does not install dependencies or call a model. An optional observed input `sha256` binds the inspected source.

Read the PNG and JSON together using available visual capabilities. Samples appear in chronological, row-major order, with actual decoded frame numbers and presentation times. Requested positions may differ from those times; short clips may map several requests to one frame. The JSON preserves those requests, the source timestamp origin, source hash and frame hashes. It records the declared duration and observed frame end separately, sampling over the longer extent so a short duration header does not hide the tail. Frames retain their full aspect ratio, including portrait footage.

Compare the requested scene, subject direction, framing and movement across the sequence. A turn or camera movement may require more samples than a static scene. Record observations needed for the requested storyboard before choosing clips. If available capabilities cannot inspect the images, report the visual decision as unresolved. A generated preview is evidence for review, not proof that a clip matches a description.

For full-clip concatenation, `scripts/assemble.py` handles frame-rate conversion, canvas padding, missing/short audio, one continuous encode, output frame/duration checks, and a timeline manifest. It uses Python's standard library plus installed `ffmpeg` and `ffprobe`; it does not install dependencies or call a model.

Create a workspace JSON spec:

```json
{"inputs":[{"path":"clips/intro.mp4"},{"path":"clips/ending.mp4"}],"video":"output/sequence.mp4","manifest":"output/sequence.json"}
```

Run `python /path/from/skill-read/scripts/assemble.py --workspace /your/workspace --spec assembly.json`. Use the actual materialized skill path returned by `read`, and the task's bound workspace. Read back the receipt and final files before reporting delivery.

Each input may include `id` and an observed `sha256`. Optional `fps`, `width`, `height` control the output; defaults follow the first video. Dimensions must be even. Outputs are H.264/AAC with one video stream and stereo 48 kHz audio; silent input is padded with silence. Alternate audio and subtitles are not included; HDR and metadata preservation are not supported. Sources are unchanged. Existing output paths are refused; reconcile them instead of replaying an unknown write.

The manifest contains `segments` in input order, with `source`, full `source_range`, and contiguous `output` intervals. Timing is quantized to output frames. The receipt includes source and output hashes, frame count and duration; these prove assembly integrity, not semantic scene selection or independent visual quality.
