# Reproduction and verification (25 October 2026)

This release uses the original supplied segmentation implementation unchanged. No reconstructed algorithm is substituted.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m stitchregions.cli demo/images/logo_drawn.png --out outputs/logo --colours 12 --hoop-mm 150 --min-region-mm2 9 --simplify-mm 0.2
```

Observed in the publication workspace with Python 3.13.5, OpenCV 4.13.0, NumPy 2.3.5:
- All 7 tests passed.
- Original synthetic logo example: 154 initial fragments merged to 8 regions, 4 final colours, smallest region 55.1 mm² at 150 mm design size.
- SVG/chart geometry agreement 99.90% with 0.2 mm smoothing, as reported by actual CLI output.

The reported reference photo measurements come from files in `examples/`, not a fresh end-to-end run of all example photographs in this environment. These outputs are a feasibility study, not a production-ready digitizer; physical thread matching requires verification against a real colour card.

## GitHub Actions verification (25 October 2026)

The [successful CI run](https://github.com/AbdulkadirKhoujja/stitch-regions/actions/runs/40235662159) for workflow commit `3c2649027b302e78c7200a0a66cd07b825d8fd36` ran the unchanged original suite on Python 3.13 under Ubuntu 24.04: **7 tests passed, zero failures or errors**. This supersedes the environment-only missing-Flask limitation for trading, but does not expand the claims about synthetic-only validation.
