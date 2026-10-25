# Stitch Regions — 90-second walkthrough narration

**Format:** silent captioned walkthrough assembled from the source project's openly licensed and original demonstration assets. A human voiceover can be recorded separately.

**00:00–00:10 — The goal.** Starting with a photo, we need a practical, simplified hand-embroidery pattern: stitchable regions, printable numbered chart and vector geometry that agrees between formats.

**00:10–00:27 — Inputs.** The prototype is demonstrated on openly licensed photographs—an astronaut, cat and coffee cup—and an original generated logo. It contains no client images.

**00:27–00:44 — Colour and regions.** Colours are clustered in perceptual CIELAB space, then fragments smaller than a specified physical area are joined to their neighbours. On the portrait example, the stored study reports a reduction from 4,889 raw fragments to 172 regions.

**00:44–01:00 — Outputs.** Regions are converted to polygons with holes. The SVG vector design and printable numbered chart draw from the same region geometry, so they remain aligned as borders are simplified.

**01:00–01:15 — Independent synthetic logo.** Running the original CLI on the drawn logo reduced 154 initial fragments to eight regions, using four thread colours at a 150-millimetre design size. The outputs are available in the repository.

**01:15–01:30 — Verification and caveats.** All seven automated tests passed. The synthetic logo's chart and polygon outputs agree on 99.90 percent of pixels with light smoothing. A full production feasibility study would need physical DMC colour verification and tests on client images, especially faces and fine details.

**Note:** the supplied video has captions but no spoken audio.