---
name: video-assembly
description: Concatenate chosen complete MP4 clips into one video and a matching segment manifest, normalizing mixed frame and audio rates. Use after clip selection; it does not identify scenes or choose storyboard matches.
---

Use available visual evidence or suitable analysis to select clips. Filenames and media metadata alone do not establish scene meaning. Keep uncertainty explicit when the available capabilities cannot confirm a match.

For full-clip concatenation, `scripts/assemble.py` handles frame-rate conversion, canvas padding, missing/short audio, one continuous encode, output frame/duration checks, and a timeline manifest. It uses Python's standard library plus installed `ffmpeg` and `ffprobe`; it does not install dependencies or call a model.

Create a workspace JSON spec:

```json
{"inputs":[{"path":"clips/intro.mp4"},{"path":"clips/ending.mp4"}],"video":"output/sequence.mp4","manifest":"output/sequence.json"}
```

Run `python /path/from/skill-read/scripts/assemble.py --workspace /your/workspace --spec assembly.json`. Use the actual materialized skill path returned by `read`, and the task's bound workspace. Read back the receipt and final files before reporting delivery.

Each input may include `id` and an observed `sha256`. Optional `fps`, `width`, `height` control the output; defaults follow the first video. Dimensions must be even. Outputs are H.264/AAC with one video stream and stereo 48 kHz audio; silent input is padded with silence. Alternate audio and subtitles are not included; HDR and metadata preservation are not supported. Sources are unchanged. Existing output paths are refused; reconcile them instead of replaying an unknown write.

The manifest contains `segments` in input order, with `source`, full `source_range`, and contiguous `output` intervals. Timing is quantized to output frames. The receipt includes source and output hashes, frame count and duration; these prove assembly integrity, not semantic scene selection or independent visual quality.
