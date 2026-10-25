"""Command line: stitchregions IMAGE --out DIR [--colours 12] [--hoop-mm 150] [--min-region-mm2 9]"""
from __future__ import annotations

import argparse
import json

from .pattern import Settings, make_pattern


def main():
    ap = argparse.ArgumentParser(description="Turn a photo into stitchable embroidery regions.")
    ap.add_argument("image")
    ap.add_argument("--out", default="outputs/pattern")
    ap.add_argument("--colours", type=int, default=12)
    ap.add_argument("--hoop-mm", type=float, default=150.0)
    ap.add_argument("--min-region-mm2", type=float, default=9.0)
    ap.add_argument("--simplify-mm", type=float, default=0.2)
    a = ap.parse_args()
    data = make_pattern(a.image, a.out, Settings(colours=a.colours, hoop_mm=a.hoop_mm, min_region_mm2=a.min_region_mm2,
                                                 simplify_mm=a.simplify_mm))
    print(json.dumps(data["metrics"], indent=2))


if __name__ == "__main__":
    main()
