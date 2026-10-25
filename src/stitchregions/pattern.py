"""Photo -> stitchable colour regions with one shared geometry for every output.

Pipeline:
  1. Edge-preserving smoothing (removes photo noise, keeps outlines).
  2. K-means colour quantisation in CIELAB (perceptual distances).
  3. Small-fragment merge: any region smaller than the minimum stitchable area
     (in mm² at the chosen hoop size) is absorbed into the neighbouring colour
     it shares the longest border with. Repeats until stable.
  4. One label map is the single source of truth. Polygons, the SVG, the
     colour-by-number chart and the JSON are all derived from it, so region
     geometry is identical across outputs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .colour import delta_e2000, lab_to_srgb, load_threads, nearest_threads, srgb_to_lab

THREADS = Path(__file__).with_name("threads_dmc_approx.csv")


@dataclass
class Settings:
    colours: int = 12
    hoop_mm: float = 150.0          # longest side of the stitched design
    min_region_mm2: float = 9.0     # smallest area worth stitching (3 x 3 mm)
    work_px: int = 600              # processing resolution (longest side)
    simplify_mm: float = 0.2        # polygon smoothing; 0 = pixel-exact polygons (100% consistent)
    seed: int = 0


def quantise(img_bgr: np.ndarray, k: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    smooth = cv2.bilateralFilter(img_bgr, 9, 40, 9)
    lab = srgb_to_lab(smooth[..., ::-1].reshape(-1, 3)).astype(np.float32)
    cv2.setRNGSeed(seed)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.2)
    _, labels, centers = cv2.kmeans(lab, k, None, crit, 4, cv2.KMEANS_PP_CENTERS)
    return labels.reshape(img_bgr.shape[:2]).astype(np.int32), centers


def merge_small_regions(labels: np.ndarray, min_px: int, max_iter: int = 30) -> tuple[np.ndarray, int]:
    labels = labels.copy()
    merged_total = 0
    kernel = np.ones((3, 3), np.uint8)
    for _ in range(max_iter):
        merged = 0
        for colour in np.unique(labels):
            mask = (labels == colour).astype(np.uint8)
            n, comp, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
            for c in range(1, n):
                if stats[c, cv2.CC_STAT_AREA] >= min_px:
                    continue
                x, y, w, h = stats[c, :4]
                x0, y0, x1, y1 = max(0, x - 2), max(0, y - 2), min(labels.shape[1], x + w + 2), min(labels.shape[0], y + h + 2)
                piece = (comp[y0:y1, x0:x1] == c).astype(np.uint8)
                ring = cv2.dilate(piece, kernel) & (1 - piece)
                neigh = labels[y0:y1, x0:x1][ring.astype(bool)]
                neigh = neigh[neigh != colour]
                if neigh.size == 0:
                    continue
                labels[y0:y1, x0:x1][piece.astype(bool)] = np.bincount(neigh).argmax()
                merged += 1
        merged_total += merged
        if merged == 0:
            break
    return labels, merged_total


def extract_regions(labels: np.ndarray, eps_px: float) -> list[dict]:
    regions = []
    for colour in np.unique(labels):
        mask = (labels == colour).astype(np.uint8)
        n, comp, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=4)
        for c in range(1, n):
            piece = (comp == c).astype(np.uint8)
            contours, hier = cv2.findContours(piece, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
            if not contours:
                continue
            outer, holes = [], []
            for i, cnt in enumerate(contours):
                poly = cv2.approxPolyDP(cnt, eps_px, True).reshape(-1, 2)
                if len(poly) < 3:
                    continue
                (holes if hier[0][i][3] >= 0 else outer).append(poly.tolist())
            if not outer:
                continue
            # label point: the pixel furthest from the region edge (always inside, even for C-shapes)
            dist = cv2.distanceTransform(np.pad(piece, 1), cv2.DIST_L2, 3)[1:-1, 1:-1]
            ly, lx = np.unravel_index(np.argmax(dist), dist.shape)
            regions.append({"colour": int(colour), "area_px": int(stats[c, cv2.CC_STAT_AREA]),
                            "outer": outer, "holes": holes, "label_point": [int(lx), int(ly)],
                            "label_room_px": float(dist[ly, lx])})
    regions.sort(key=lambda r: -r["area_px"])
    for i, r in enumerate(regions, start=1):
        r["id"] = i
    return regions


def make_pattern(image_path: str, out_dir: str, s: Settings = Settings()) -> dict:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    src = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if src is None:
        raise FileNotFoundError(image_path)
    scale = s.work_px / max(src.shape[:2])
    img = cv2.resize(src, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else src.copy()
    h, w = img.shape[:2]
    mm_per_px = s.hoop_mm / max(h, w)
    min_px = max(4, int(round(s.min_region_mm2 / mm_per_px ** 2)))

    labels, centers_lab = quantise(img, s.colours, s.seed)
    raw_regions = sum(cv2.connectedComponents((labels == c).astype(np.uint8), connectivity=4)[0] - 1 for c in np.unique(labels))
    labels, merged = merge_small_regions(labels, min_px)
    # Colours that land on the same thread are one colour to a stitcher: merge them.
    thread_list = load_threads(THREADS)
    matched = nearest_threads(lab_to_srgb(centers_lab), thread_list)
    groups: dict[str, list[int]] = {}
    for c in np.unique(labels):
        groups.setdefault(matched[int(c)][0].code, []).append(int(c))
    lut = np.zeros(len(centers_lab), np.int32)
    new_centers = []
    for gi, members in enumerate(groups.values()):
        weights = np.array([(labels == m).sum() for m in members], float)
        new_centers.append((centers_lab[members] * weights[:, None]).sum(0) / weights.sum())
        lut[members] = gi
    labels = lut[labels]
    centers_lab = np.array(new_centers)
    labels, merged2 = merge_small_regions(labels, min_px)
    merged += merged2
    palette_rgb = lab_to_srgb(centers_lab)
    threads = nearest_threads(palette_rgb, thread_list)
    colours_requested = s.colours

    regions = extract_regions(labels, s.simplify_mm / mm_per_px)
    for r in regions:
        r["area_mm2"] = round(r["area_px"] * mm_per_px ** 2, 1)
    # The simplified polygons are the final geometry. Re-rasterise them so the chart, preview, SVG and JSON
    # all describe exactly the same shapes; record how closely they follow the original segmentation.
    seg_fidelity = geometry_agreement(regions, labels)
    labels = rasterise(regions, labels)

    # colour fidelity: per-pixel CIEDE2000 between the (unsmoothed) photo and the pattern colours
    photo_lab = srgb_to_lab(img[..., ::-1].reshape(-1, 3))
    pat_lab = centers_lab[labels.reshape(-1)]
    de = delta_e2000(photo_lab, pat_lab)

    counts = np.bincount(labels.reshape(-1), minlength=len(palette_rgb))
    palette = []
    for i, (rgb, (thread, de_t)) in enumerate(zip(palette_rgb, threads)):
        palette.append({"index": i + 1, "rgb": [int(v) for v in rgb], "hex": "#%02x%02x%02x" % tuple(int(v) for v in rgb),
                        "share_pct": round(100 * counts[i] / labels.size, 1),
                        "regions": sum(1 for r in regions if r["colour"] == i),
                        "thread": {"brand": "DMC (approx.)", "code": thread.code, "name": thread.name,
                                   "delta_e2000": round(de_t, 1)}})

    metrics = {
        "image": Path(image_path).name, "work_size_px": [w, h], "design_size_mm": [round(w * mm_per_px, 1), round(h * mm_per_px, 1)],
        "colours_requested": colours_requested, "colours": len(palette_rgb), "regions": len(regions), "regions_before_merge": int(raw_regions), "fragments_merged": int(merged),
        "smallest_region_mm2": min(r["area_mm2"] for r in regions), "min_region_mm2_setting": s.min_region_mm2,
        "mean_delta_e2000": round(float(de.mean()), 2), "p90_delta_e2000": round(float(np.percentile(de, 90)), 2),
        "mean_thread_delta_e2000": round(float(np.mean([t[1] for t in threads])), 2),
    }

    _write_svg(out / "pattern.svg", regions, palette, w, h, mm_per_px)
    _write_chart(out / "colour_by_number.png", regions, palette, labels)
    filled = palette_rgb[labels][..., ::-1]
    cv2.imwrite(str(out / "preview.png"), filled)
    cv2.imwrite(str(out / "labels.png"), labels.astype(np.uint16))  # rasterised final geometry
    metrics["polygon_vs_segmentation_pct"] = seg_fidelity
    metrics["outputs_consistency_pct"] = geometry_agreement(regions, labels)
    _write_comparison(out / "comparison.png", img, filled, out / "colour_by_number.png")
    data = {"settings": s.__dict__, "metrics": metrics, "palette": palette,
            "regions": [{k: r[k] for k in ("id", "colour", "area_mm2", "label_point", "outer", "holes")} for r in regions]}
    (out / "regions.json").write_text(json.dumps(data))
    (out / "metrics.json").write_text(json.dumps({"metrics": metrics, "palette": palette}, indent=2))
    return data


def _draw(regions: list[dict], shape) -> np.ndarray:
    canvas = np.full(shape, -1, np.int32)
    for r in sorted(regions, key=lambda r: -r["area_px"]):  # big first, small regions drawn on top
        m = np.zeros(shape, np.uint8)
        cv2.fillPoly(m, [np.array(p, np.int32) for p in r["outer"]], 1)
        if r["holes"]:
            holes = [np.array(p, np.int32) for p in r["holes"]]
            cv2.fillPoly(m, holes, 0)
            cv2.polylines(m, holes, True, 1)  # a hole's outline is traced on this region's own pixels
        canvas[m.astype(bool)] = r["colour"]
    return canvas


def rasterise(regions: list[dict], fallback: np.ndarray) -> np.ndarray:
    """Final label map drawn from the polygons; any hairline gap keeps its original colour."""
    canvas = _draw(regions, fallback.shape)
    return np.where(canvas >= 0, canvas, fallback).astype(np.int32)


def geometry_agreement(regions: list[dict], labels: np.ndarray) -> float:
    """Redraw every exported polygon (outer minus holes) and compare with the label map, pixel by pixel.

    Returns the % of pixels whose colour in the exported polygons matches the label map. This is the
    check that the SVG / JSON geometry and the colour-by-number chart describe the same regions.
    """
    return round(float((_draw(regions, labels.shape) == labels).mean() * 100), 2)


def _path(poly) -> str:
    return "M" + " L".join(f"{x} {y}" for x, y in poly) + " Z"


def _write_svg(path: Path, regions, palette, w, h, mm_per_px):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
             f'width="{w * mm_per_px:.1f}mm" height="{h * mm_per_px:.1f}mm">']
    for r in regions:
        d = " ".join(_path(p) for p in r["outer"] + r["holes"])
        col = palette[r["colour"]]["hex"]
        # stroke in the fill colour closes hairline gaps between neighbouring simplified polygons
        parts.append(f'<path id="r{r["id"]}" d="{d}" fill="{col}" fill-rule="evenodd" stroke="{col}" stroke-width="0.8" '
                     f'data-colour="{r["colour"] + 1}" data-thread="DMC {palette[r["colour"]]["thread"]["code"]}"/>')
    parts.append("</svg>")
    path.write_text("\n".join(parts))


def _write_chart(path: Path, regions, palette, labels, scale: int = 2):
    h, w = labels.shape
    W, H = w * scale, h * scale
    legend_h = 40 + 28 * ((len(palette) + 2) // 3)
    img = np.full((H + legend_h, W, 3), 255, np.uint8)
    # Borders come straight from the shared label map, so each edge between two regions is drawn exactly once.
    big = cv2.resize(labels.astype(np.uint16), (W, H), interpolation=cv2.INTER_NEAREST)
    edge = np.zeros((H, W), bool)
    edge[:, 1:] |= big[:, 1:] != big[:, :-1]
    edge[1:, :] |= big[1:, :] != big[:-1, :]
    edge[[0, -1], :] = True; edge[:, [0, -1]] = True
    img[:H][edge] = (40, 40, 40)
    for r in regions:
        if r["label_room_px"] * scale < 6:
            continue  # too small to print a readable number; the region is still in the SVG and JSON
        x, y = r["label_point"]
        txt = str(r["colour"] + 1)
        fs = 0.32 if r["label_room_px"] * scale < 10 else 0.42
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
        cv2.putText(img, txt, (x * scale - tw // 2, y * scale + th // 2), cv2.FONT_HERSHEY_SIMPLEX, fs, (60, 60, 60), 1, cv2.LINE_AA)
    for i, p in enumerate(palette):
        cx, cy = 12 + (i % 3) * (W // 3), H + 20 + 28 * (i // 3)
        cv2.rectangle(img, (cx, cy), (cx + 20, cy + 18), tuple(int(v) for v in p["rgb"][::-1]), -1)
        cv2.rectangle(img, (cx, cy), (cx + 20, cy + 18), (60, 60, 60), 1)
        cv2.putText(img, f'{p["index"]}: DMC {p["thread"]["code"]} {p["thread"]["name"]}'[:34], (cx + 26, cy + 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (30, 30, 30), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), img)


def _write_comparison(path: Path, original, filled, chart_path: Path):
    chart = cv2.imread(str(chart_path))
    h = original.shape[0]
    chart = cv2.resize(chart[: chart.shape[0] - (chart.shape[0] - 2 * h)], (original.shape[1], h), interpolation=cv2.INTER_AREA)
    gap = np.full((h, 8, 3), 255, np.uint8)
    cv2.imwrite(str(path), np.hstack([original, gap, filled, gap, chart]))
