"""Run: PYTHONPATH=src python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stitchregions.colour import delta_e2000, lab_to_srgb, srgb_to_lab  # noqa: E402
from stitchregions.pattern import Settings, make_pattern, merge_small_regions  # noqa: E402


class TestColour(unittest.TestCase):
    def test_lab_roundtrip(self):
        rgb = np.array([[0, 0, 0], [255, 255, 255], [200, 30, 60], [10, 120, 240]], np.uint8)
        self.assertTrue(np.abs(lab_to_srgb(srgb_to_lab(rgb)).astype(int) - rgb).max() <= 1)

    def test_white_lab(self):
        L, a, b = srgb_to_lab(np.array([255, 255, 255]))
        self.assertAlmostEqual(L, 100, delta=0.05); self.assertAlmostEqual(a, 0, delta=0.05)

    def test_ciede2000_reference_pairs(self):
        # Published CIEDE2000 test data (Sharma, Wu & Dalal 2005), pairs 1 and 7
        pairs = [((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
                 ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669)]
        for a, b, expected in pairs:
            self.assertAlmostEqual(float(delta_e2000(np.array(a), np.array(b))), expected, places=3)


class TestMerge(unittest.TestCase):
    def test_small_fragment_absorbed_by_surroundings(self):
        labels = np.zeros((40, 40), np.int32)
        labels[20:22, 20:22] = 1          # 4 px speck
        labels[:, 30:] = 2
        out, merged = merge_small_regions(labels, min_px=10)
        self.assertEqual(merged, 1)
        self.assertEqual(int(out[20, 20]), 0)
        self.assertTrue((out[:, 30:] == 2).all())  # big region untouched


class TestEndToEnd(unittest.TestCase):
    def _run(self, image, **kw):
        tmp = tempfile.mkdtemp()
        data = make_pattern(str(ROOT / "demo/images" / image), tmp, Settings(**kw))
        return tmp, data

    def test_outputs_and_constraints(self):
        tmp, data = self._run("pet_chelsea.png", colours=12, hoop_mm=150, min_region_mm2=9)
        for f in ("pattern.svg", "colour_by_number.png", "preview.png", "regions.json", "metrics.json", "labels.png"):
            self.assertTrue((Path(tmp) / f).exists(), f)
        m = data["metrics"]
        self.assertGreaterEqual(m["smallest_region_mm2"], 9.0 * 0.9)   # within rounding of the setting
        self.assertLess(m["regions"], m["regions_before_merge"])
        self.assertGreaterEqual(m["outputs_consistency_pct"], 99.5)
        self.assertGreaterEqual(m["polygon_vs_segmentation_pct"], 95.0)
        self.assertEqual(len({p["thread"]["code"] for p in data["palette"]}), len(data["palette"]))  # no duplicate threads
        svg = (Path(tmp) / "pattern.svg").read_text()
        self.assertEqual(svg.count("<path "), m["regions"])
        self.assertIn('width="150.0mm"', svg)

    def test_bigger_min_area_means_fewer_regions(self):
        _, small = self._run("object_coffee.png", min_region_mm2=4)
        _, big = self._run("object_coffee.png", min_region_mm2=25)
        self.assertLess(big["metrics"]["regions"], small["metrics"]["regions"])
        self.assertGreaterEqual(big["metrics"]["smallest_region_mm2"], 25 * 0.9)

    def test_deterministic(self):
        _, a = self._run("logo_drawn.png")
        _, b = self._run("logo_drawn.png")
        self.assertEqual(json.dumps(a["regions"]), json.dumps(b["regions"]))


if __name__ == "__main__":
    unittest.main()
