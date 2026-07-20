#!/usr/bin/env python3
"""
Steel plate nesting engine  (rectangular / bounding-box)
=========================================================
A self-contained nesting + estimating tool for a fabrication shop.

Reliable:
  * Nests parts onto stock plates with a MaxRects bin-packing algorithm
    (rotation, kerf + gap spacing, edge margin, multiple plate sizes,
    greedy multi-plate fill). Rectangular parts nest exactly.
  * Parts can carry HOLES (round) and rectangular CUTOUTS -- subtracted
    from weight/cost, rotated with the part, drawn in the layout, and cut
    as real geometry in the DXF output.
  * Yield / scrap / largest reusable drop, part weight, material cost.
  * Labeled layout (PNG per plate + combined PDF).
  * DXF outputs:
      - nest.dxf              all plates side-by-side (overview/reference)
      - burn_plate_N.dxf      ONE FILE PER SHEET for the burn table:
                              part profiles on layer PROFILE, holes on
                              layer HOLES, origin at the sheet corner.

Deliberately NOT done:
  * True-shape nesting of irregular parts (they nest by BOUNDING BOX,
    clearly flagged). Supply a part `area` for exact weight on those.
  * Machine-ready G-code / NC with kerf comp, pierce points and lead-ins
    for a specific controller. The burn-table DXF is an import file; the
    machine's own CAM/post applies those (that is where they belong).

Usage:
  python3 nest.py --job job.json --out out/
"""

import argparse
import json
import math
import os
from dataclasses import dataclass, field

STEEL_DENSITY = 0.2836  # lb/in^3, A36 mild steel


# --------------------------------------------------------------------------
# Geometry primitives
# --------------------------------------------------------------------------
@dataclass
class FreeRect:
    x: float
    y: float
    w: float
    h: float


@dataclass
class Placement:
    part_id: str
    label: str
    x: float                 # placed lower-left, usable (post-margin) coords
    y: float
    w: float                 # placed footprint (post-rotation)
    h: float
    rotated: bool
    shape: str               # "rect" | "irregular"
    ow: float                # original (unrotated) part width
    oh: float                # original (unrotated) part height
    holes: list = field(default_factory=list)   # in original part coords
    base_area: float = 0.0   # gross area (bbox for rect, declared area for irregular)
    holes_area: float = 0.0  # total area removed by holes/cutouts


class MaxRectsBin:
    """One stock plate packed with MaxRects (Best-Short-Side-Fit)."""

    EPS = 1e-9

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.free = [FreeRect(0.0, 0.0, width, height)]
        self.placements = []

    def insert(self, w, h, allow_rotate=True):
        best = self._find(w, h, allow_rotate)
        if best is None:
            return None
        x, y, pw, ph, rotated = best
        self._place_and_split(x, y, pw, ph)
        return best

    def _find(self, w, h, allow_rotate):
        best_short = math.inf
        best_long = math.inf
        best = None
        candidates = [(w, h, False)]
        if allow_rotate:
            candidates.append((h, w, True))
        for fr in self.free:
            for cw, ch, rot in candidates:
                if fr.w + self.EPS >= cw and fr.h + self.EPS >= ch:
                    lh = abs(fr.w - cw)
                    lv = abs(fr.h - ch)
                    short = min(lh, lv)
                    long_ = max(lh, lv)
                    if (short < best_short - self.EPS or
                            (abs(short - best_short) <= self.EPS and long_ < best_long)):
                        best_short, best_long = short, long_
                        best = (fr.x, fr.y, cw, ch, rot)
        return best

    def _place_and_split(self, x, y, w, h):
        placed = FreeRect(x, y, w, h)
        new_free = []
        for fr in self.free:
            if self._overlaps(fr, placed):
                new_free.extend(self._split(fr, placed))
            else:
                new_free.append(fr)
        self.free = new_free
        self._prune()

    @classmethod
    def _overlaps(cls, a, b):
        return not (b.x >= a.x + a.w - cls.EPS or b.x + b.w <= a.x + cls.EPS or
                    b.y >= a.y + a.h - cls.EPS or b.y + b.h <= a.y + cls.EPS)

    @classmethod
    def _split(cls, fr, placed):
        out = []
        if placed.x > fr.x + cls.EPS:
            out.append(FreeRect(fr.x, fr.y, placed.x - fr.x, fr.h))
        if placed.x + placed.w < fr.x + fr.w - cls.EPS:
            out.append(FreeRect(placed.x + placed.w, fr.y,
                                fr.x + fr.w - (placed.x + placed.w), fr.h))
        if placed.y > fr.y + cls.EPS:
            out.append(FreeRect(fr.x, fr.y, fr.w, placed.y - fr.y))
        if placed.y + placed.h < fr.y + fr.h - cls.EPS:
            out.append(FreeRect(fr.x, placed.y + placed.h, fr.w,
                                fr.y + fr.h - (placed.y + placed.h)))
        return out

    def _prune(self):
        n = len(self.free)
        dead = [False] * n
        for i in range(n):
            if dead[i]:
                continue
            for j in range(n):
                if i == j or dead[j]:
                    continue
                if self._contains(self.free[j], self.free[i]):
                    dead[i] = True
                    break
        self.free = [f for k, f in enumerate(self.free)
                     if not dead[k] and f.w > 1e-6 and f.h > 1e-6]

    @classmethod
    def _contains(cls, outer, inner):
        return (inner.x >= outer.x - cls.EPS and inner.y >= outer.y - cls.EPS and
                inner.x + inner.w <= outer.x + outer.w + cls.EPS and
                inner.y + inner.h <= outer.y + outer.h + cls.EPS)

    def largest_free(self):
        return max(self.free, key=lambda r: r.w * r.h) if self.free else None


# --------------------------------------------------------------------------
# Holes
# --------------------------------------------------------------------------
def hole_area(hole):
    """Area removed by a single hole/cutout (in^2)."""
    if hole.get("dia") is not None:
        return math.pi * (float(hole["dia"]) / 2.0) ** 2
    if hole.get("w") is not None and hole.get("h") is not None:   # rect cutout
        return float(hole["w"]) * float(hole["h"])
    return 0.0


def hole_local(pc, hole):
    """
    Hole center in the PLACED part's local frame (0..pw, 0..ph),
    accounting for a 90-degree rotation. `pc` is a placement dict.
    """
    hx, hy = float(hole["x"]), float(hole["y"])
    if pc["rotated"]:
        # 90deg CCW: (x,y) -> (oh - y, x) inside placed box (oh wide, ow tall)
        return pc["oh"] - hy, hx
    return hx, hy


# --------------------------------------------------------------------------
# Job runner
# --------------------------------------------------------------------------
def run_job(job):
    s = job.get("settings", {})
    kerf = float(s.get("kerf_in", 0.06))
    gap = float(s.get("part_gap_in", 0.25))
    margin = float(s.get("edge_margin_in", 0.5))
    density = float(s.get("density_lb_in3", STEEL_DENSITY))
    spacing = kerf + gap

    # expand parts, largest first
    units = []
    for p in job["parts"]:
        holes = p.get("holes", []) or []
        h_area = sum(hole_area(h) for h in holes)
        base = float(p["width"]) * float(p["height"])
        if p.get("shape") == "irregular" and p.get("area"):
            base = float(p["area"])
        for _ in range(int(p.get("qty", 1))):
            units.append({
                "part_id": p["name"], "label": p["name"],
                "w": float(p["width"]), "h": float(p["height"]),
                "rotatable": bool(p.get("rotatable", True)),
                "shape": p.get("shape", "rect"),
                "holes": holes, "base_area": base, "holes_area": h_area,
            })
    units.sort(key=lambda u: u["w"] * u["h"], reverse=True)

    stock_types = []
    for st in job["stock"]:
        stock_types.append({
            "name": st.get("name", "Plate"),
            "W": float(st["width"]), "H": float(st["height"]),
            "thickness": float(st.get("thickness", s.get("thickness_in", 0.5))),
            "qty": math.inf if st.get("unlimited") else int(st.get("qty", 1)),
            "cost_per_lb": st.get("cost_per_lb"),
            "cost_per_sheet": st.get("cost_per_sheet"),
            "used": 0,
        })

    plates = []

    def open_plate(fit=None):
        for stype in stock_types:
            if stype["used"] >= stype["qty"]:
                continue
            uw, uh = stype["W"] - 2 * margin, stype["H"] - 2 * margin
            if fit is not None:
                fw, fh = fit["w"] + spacing, fit["h"] + spacing
                ok = (fw <= uw + 1e-9 and fh <= uh + 1e-9)
                if fit["rotatable"]:
                    ok = ok or (fh <= uw + 1e-9 and fw <= uh + 1e-9)
                if not ok:
                    continue
            stype["used"] += 1
            plates.append({"stock": stype, "bin": MaxRectsBin(uw, uh), "placements": []})
            return plates[-1]
        return None

    def fits_any(u):
        fw, fh = u["w"] + spacing, u["h"] + spacing
        for stype in stock_types:
            uw, uh = stype["W"] - 2 * margin, stype["H"] - 2 * margin
            if (fw <= uw + 1e-9 and fh <= uh + 1e-9) or \
               (u["rotatable"] and fh <= uw + 1e-9 and fw <= uh + 1e-9):
                return True
        return False

    def commit(pl, u, res):
        x, y, rw, rh, rot = res
        pl["placements"].append(Placement(
            u["part_id"], u["label"], x, y, rw - spacing, rh - spacing, rot,
            u["shape"], u["w"], u["h"], u["holes"], u["base_area"], u["holes_area"]))

    unplaced = []
    for u in units:
        if not fits_any(u):
            unplaced.append(u)
            continue
        fw, fh = u["w"] + spacing, u["h"] + spacing
        placed = False
        for pl in plates:
            res = pl["bin"].insert(fw, fh, u["rotatable"])
            if res:
                commit(pl, u, res)
                placed = True
                break
        if not placed:
            newpl = open_plate(fit=u)
            if newpl is not None:
                res = newpl["bin"].insert(fw, fh, u["rotatable"])
                if res:
                    commit(newpl, u, res)
                    placed = True
        if not placed:
            unplaced.append(u)

    used_plates = [pl for pl in plates if pl["placements"]]
    for i, pl in enumerate(used_plates, 1):
        pl["index"] = i

    return _summarize(job, used_plates, unplaced, density, margin, kerf, gap)


def _summarize(job, used_plates, unplaced, density, margin, kerf, gap):
    plate_reports = []
    tot_plate_area = tot_part_area_bbox = 0.0
    tot_plate_wt = tot_part_wt = 0.0
    tot_cost = 0.0
    cost_known = True
    part_net = {}

    for pl in used_plates:
        stype = pl["stock"]
        W, H, t = stype["W"], stype["H"], stype["thickness"]
        plate_area = W * H
        plate_wt = plate_area * t * density

        p_area_bbox = p_wt = 0.0
        n_holes = 0
        parts_on = {}
        for pc in pl["placements"]:
            bbox = pc.w * pc.h
            net_area = max(0.0, pc.base_area - pc.holes_area)
            p_area_bbox += bbox
            wt = net_area * t * density
            p_wt += wt
            n_holes += len(pc.holes)
            parts_on[pc.label] = parts_on.get(pc.label, 0) + 1
            if stype.get("cost_per_lb") is not None:
                part_net[pc.label] = part_net.get(pc.label, 0.0) + wt * float(stype["cost_per_lb"])

        if stype.get("cost_per_sheet") is not None:
            plate_cost = float(stype["cost_per_sheet"])
        elif stype.get("cost_per_lb") is not None:
            plate_cost = plate_wt * float(stype["cost_per_lb"])
        else:
            plate_cost = None
            cost_known = False

        lf = pl["bin"].largest_free()
        remnant = (round(lf.w, 2), round(lf.h, 2)) if lf else None

        plate_reports.append({
            "index": pl["index"], "stock": stype["name"],
            "size": f"{_fmt(W)} x {_fmt(H)} x {_fmt(t)}",
            "W": W, "H": H, "thickness": t,
            "parts": parts_on, "num_parts": len(pl["placements"]), "num_holes": n_holes,
            "yield_pct": round(100 * p_area_bbox / plate_area, 1),
            "plate_weight_lb": round(plate_wt, 1),
            "part_weight_lb": round(p_wt, 1),
            "scrap_weight_lb": round(plate_wt - p_wt, 1),
            "plate_cost": None if plate_cost is None else round(plate_cost, 2),
            "largest_remnant": remnant,
            "placements": [vars(pc) for pc in pl["placements"]],
        })

        tot_plate_area += plate_area
        tot_part_area_bbox += p_area_bbox
        tot_plate_wt += plate_wt
        tot_part_wt += p_wt
        if plate_cost is not None:
            tot_cost += plate_cost

    overall_yield = round(100 * tot_part_area_bbox / tot_plate_area, 1) if tot_plate_area else 0.0

    res = {
        "meta": {
            "job_name": job.get("job_name", "Nesting job"),
            "customer": job.get("customer", ""),
            "kerf_in": kerf, "part_gap_in": gap, "edge_margin_in": margin,
            "density_lb_in3": density,
        },
        "plates_used": len(used_plates),
        "overall_yield_pct": overall_yield,
        "total_plate_weight_lb": round(tot_plate_wt, 1),
        "total_part_weight_lb": round(tot_part_wt, 1),
        "total_scrap_weight_lb": round(tot_plate_wt - tot_part_wt, 1),
        "total_material_cost": None if not cost_known else round(tot_cost, 2),
        "cost_known": cost_known,
        "total_holes": sum(pr["num_holes"] for pr in plate_reports),
        "part_net_cost": {k: round(v, 2) for k, v in part_net.items()},
        "plate_reports": plate_reports,
        "unplaced": [{"label": u["label"], "size": f'{_fmt(u["w"])} x {_fmt(u["h"])}'}
                     for u in unplaced],
        "has_irregular": any(p.get("shape") == "irregular" for p in job["parts"]),
    }
    res["rfq_nesting"] = rfq_nesting_block(res)
    return res


def _fmt(v):
    return f"{v:g}"


# --------------------------------------------------------------------------
# RFQ hand-off block  (feeds steel-rfq "Nesting / Drop Reference" table)
# --------------------------------------------------------------------------
def rfq_nesting_block(res):
    """Group plates by stock material -> Material | Nesting Plan | Drop Notes rows."""
    from collections import defaultdict
    groups = defaultdict(list)
    for pr in res["plate_reports"]:
        groups[pr["stock"]].append(pr)

    blocks = []
    for name, prs in groups.items():
        sheets = len(prs)
        W, H = prs[0]["W"], prs[0]["H"]
        pa = sum(pr["yield_pct"] / 100 * pr["W"] * pr["H"] for pr in prs)
        ta = sum(pr["W"] * pr["H"] for pr in prs)
        yld = round(100 * pa / ta, 1) if ta else 0.0
        parts = sum(pr["num_parts"] for pr in prs)
        drops = sorted([pr["largest_remnant"] for pr in prs if pr["largest_remnant"]],
                       key=lambda d: d[0] * d[1], reverse=True)[:3]
        drop_txt = "; ".join(f"{_fmt(d[0])}x{_fmt(d[1])}" for d in drops) or "minimal"
        cost = sum((pr["plate_cost"] or 0) for pr in prs)
        blocks.append({
            "material": name,
            "sheets_needed": sheets,
            "sheet_size": f"{_fmt(W)}x{_fmt(H)}",
            "yield_pct": yld,
            "nesting_plan": f"{sheets} x {_fmt(W)}x{_fmt(H)} sheet(s) - {yld}% yield, {parts} parts",
            "drop_notes": f"Largest reusable drops: {drop_txt} in",
            "total_cost": round(cost, 2) if res["cost_known"] else None,
        })
    return blocks


# --------------------------------------------------------------------------
# Text report
# --------------------------------------------------------------------------
def render_text(res):
    m = res["meta"]
    L = ["=" * 64, f"  NEST REPORT — {m['job_name']}"]
    if m.get("customer"):
        L.append(f"  Customer: {m['customer']}")
    L.append("=" * 64)
    L.append(f"  Kerf {m['kerf_in']}\"  |  Part gap {m['part_gap_in']}\"  |  "
             f"Edge margin {m['edge_margin_in']}\"  |  {m['density_lb_in3']} lb/in^3")
    L.append("")
    L.append(f"  Plates used ............ {res['plates_used']}")
    L.append(f"  Overall yield .......... {res['overall_yield_pct']}%")
    L.append(f"  Holes / cutouts ........ {res['total_holes']}")
    L.append(f"  Total plate weight ..... {res['total_plate_weight_lb']} lb")
    L.append(f"  Net part weight ........ {res['total_part_weight_lb']} lb  (holes removed)")
    L.append(f"  Scrap weight ........... {res['total_scrap_weight_lb']} lb")
    if res["cost_known"]:
        L.append(f"  Material cost (plates) . ${res['total_material_cost']:,.2f}")
    else:
        L.append("  Material cost .......... (add cost_per_lb or cost_per_sheet to stock)")
    L.append("")
    L.append("  " + "-" * 60)
    for pr in res["plate_reports"]:
        parts_str = ", ".join(f"{lbl} x{n}" for lbl, n in pr["parts"].items())
        L.append(f"  PLATE {pr['index']} — {pr['stock']}  ({pr['size']} in)")
        L.append(f"    Parts:   {parts_str}")
        L.append(f"    Holes:   {pr['num_holes']}")
        L.append(f"    Yield:   {pr['yield_pct']}%   "
                 f"Part wt {pr['part_weight_lb']} lb / plate {pr['plate_weight_lb']} lb   "
                 f"Scrap {pr['scrap_weight_lb']} lb")
        if pr["plate_cost"] is not None:
            L.append(f"    Cost:    ${pr['plate_cost']:,.2f}")
        if pr["largest_remnant"]:
            rw, rh = pr["largest_remnant"]
            L.append(f"    Biggest usable drop: {_fmt(rw)} x {_fmt(rh)} in")
        L.append("")
    if res["part_net_cost"]:
        L.append("  Net material cost per part (metal in part, before markup):")
        for lbl, c in res["part_net_cost"].items():
            L.append(f"    {lbl:<22} ${c:,.2f}")
        L.append("")
    if res["unplaced"]:
        L.append("  " + "!" * 60)
        L.append("  DID NOT FIT (need more/larger stock):")
        for u in res["unplaced"]:
            L.append(f"    - {u['label']}  ({u['size']} in)")
        L.append("")
    if res["has_irregular"]:
        L.append("  NOTE: irregular parts are nested by BOUNDING BOX. Supply a")
        L.append("  true `area` per irregular part for exact weight/cost.")
    L.append("=" * 64)
    return "\n".join(L)


# --------------------------------------------------------------------------
# Visual layout  (PNG per plate + combined PDF), holes drawn
# --------------------------------------------------------------------------
def render_layout(res, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.backends.backend_pdf import PdfPages

    margin = res["meta"]["edge_margin_in"]
    pdf_path = os.path.join(outdir, "layout.pdf")
    png_paths = []

    with PdfPages(pdf_path) as pdf:
        for pr in res["plate_reports"]:
            W, H = pr["W"], pr["H"]
            fig, ax = plt.subplots(figsize=(11, max(4.0, 11 * H / W)))
            ax.add_patch(mpatches.Rectangle((0, 0), W, H, fill=False, lw=2.0, ec="#222"))
            ax.add_patch(mpatches.Rectangle((margin, margin), W - 2 * margin, H - 2 * margin,
                                            fill=False, lw=0.8, ec="#bbb", ls="--"))
            for pc in pr["placements"]:
                x, y = pc["x"] + margin, pc["y"] + margin
                w, h = pc["w"], pc["h"]
                irregular = pc["shape"] == "irregular"
                face = "#f4c9a0" if irregular else "#a9c8e8"
                ax.add_patch(mpatches.Rectangle((x, y), w, h, facecolor=face,
                                                edgecolor="#1a3b5c", lw=1.2,
                                                hatch="///" if irregular else None, alpha=0.9))
                for hole in pc.get("holes", []):
                    lx, ly = hole_local(pc, hole)
                    cx, cy = x + lx, y + ly
                    if hole.get("dia") is not None:
                        ax.add_patch(mpatches.Circle((cx, cy), float(hole["dia"]) / 2.0,
                                                     facecolor="white", edgecolor="#8a1c1c", lw=1.0))
                    elif hole.get("w") is not None:
                        hw, hh = float(hole["w"]), float(hole["h"])
                        if pc["rotated"]:
                            hw, hh = hh, hw
                        ax.add_patch(mpatches.Rectangle((cx - hw / 2, cy - hh / 2), hw, hh,
                                                        facecolor="white", edgecolor="#8a1c1c", lw=1.0))
                lbl = pc["label"] + ("*" if irregular else "") + ("  ⟳" if pc["rotated"] else "")
                ax.text(x + w / 2, y + h / 2, lbl, ha="center", va="center",
                        fontsize=7, color="#0c2233")
            ax.set_xlim(-1, W + 1)
            ax.set_ylim(-1, H + 1)
            ax.set_aspect("equal")
            ax.set_title(f"PLATE {pr['index']} — {pr['stock']}  ({pr['size']} in)   "
                         f"Yield {pr['yield_pct']}%   Holes {pr['num_holes']}",
                         fontsize=12, fontweight="bold")
            ax.set_xlabel("inches")
            ax.grid(True, lw=0.3, color="#eee")
            png = os.path.join(outdir, f"plate_{pr['index']}.png")
            fig.savefig(png, dpi=110, bbox_inches="tight")
            png_paths.append(png)
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)

        fig = plt.figure(figsize=(11, 8.5))
        fig.text(0.5, 0.94, "NEST SUMMARY", ha="center", fontsize=18, fontweight="bold")
        fig.text(0.06, 0.88, render_text(res), family="monospace", fontsize=8.0, va="top")
        pdf.savefig(fig)
        plt.close(fig)

    return pdf_path, png_paths


# --------------------------------------------------------------------------
# DXF: overview (all plates) + one burn file per sheet
# --------------------------------------------------------------------------
def _draw_part_dxf(msp, pc, x0, y0, profile_layer, holes_layer, notes_layer, label=True):
    import ezdxf
    x, y = x0 + pc["x"], y0 + pc["y"]
    w, h = pc["w"], pc["h"]
    msp.add_lwpolyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)],
                       dxfattribs={"layer": profile_layer, "closed": True})
    for hole in pc.get("holes", []):
        lx, ly = hole_local(pc, hole)
        cx, cy = x + lx, y + ly
        if hole.get("dia") is not None:
            msp.add_circle((cx, cy), float(hole["dia"]) / 2.0, dxfattribs={"layer": holes_layer})
        elif hole.get("w") is not None:
            hw, hh = float(hole["w"]), float(hole["h"])
            if pc["rotated"]:
                hw, hh = hh, hw
            msp.add_lwpolyline(
                [(cx - hw / 2, cy - hh / 2), (cx + hw / 2, cy - hh / 2),
                 (cx + hw / 2, cy + hh / 2), (cx - hw / 2, cy + hh / 2), (cx - hw / 2, cy - hh / 2)],
                dxfattribs={"layer": holes_layer, "closed": True})
    if label:
        msp.add_text(pc["label"], height=min(1.0, max(0.25, min(w, h) * 0.18)),
                     dxfattribs={"layer": notes_layer}).set_placement(
            (x + w / 2, y + h / 2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)


def render_dxf_overview(res, outdir):
    import ezdxf
    margin = res["meta"]["edge_margin_in"]
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.IN
    msp = doc.modelspace()
    for lyr, col in [("PLATE", 5), ("PROFILE", 3), ("HOLES", 1), ("NOTES", 7)]:
        if lyr not in doc.layers:
            doc.layers.add(lyr, color=col)
    x_off = 0.0
    for pr in res["plate_reports"]:
        W, H = pr["W"], pr["H"]
        msp.add_lwpolyline([(x_off, 0), (x_off + W, 0), (x_off + W, H), (x_off, H), (x_off, 0)],
                           dxfattribs={"layer": "PLATE", "closed": True})
        for pc in pr["placements"]:
            _draw_part_dxf(msp, pc, x_off + margin, margin, "PROFILE", "HOLES", "NOTES")
        x_off += W + 10.0
    path = os.path.join(outdir, "nest.dxf")
    doc.saveas(path)
    return path


def render_burn_dxfs(res, outdir):
    """One DXF per sheet for the burn table. Origin at sheet corner."""
    import ezdxf
    margin = res["meta"]["edge_margin_in"]
    paths = []
    for pr in res["plate_reports"]:
        doc = ezdxf.new("R2010")
        doc.units = ezdxf.units.IN
        msp = doc.modelspace()
        for lyr, col in [("PLATE", 5), ("PROFILE", 3), ("HOLES", 1), ("NOTES", 7)]:
            doc.layers.add(lyr, color=col)
        W, H = pr["W"], pr["H"]
        # sheet outline for reference (delete on the table if not wanted)
        msp.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H), (0, 0)],
                           dxfattribs={"layer": "PLATE", "closed": True})
        for pc in pr["placements"]:
            _draw_part_dxf(msp, pc, margin, margin, "PROFILE", "HOLES", "NOTES")
        path = os.path.join(outdir, f"burn_plate_{pr['index']}.dxf")
        doc.saveas(path)
        paths.append(path)
    return paths


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Steel plate nesting engine")
    ap.add_argument("--job", required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--no-render", action="store_true", help="Skip PDF/PNG/DXF")
    args = ap.parse_args()

    with open(args.job) as f:
        job = json.load(f)
    os.makedirs(args.out, exist_ok=True)

    res = run_job(job)

    report = render_text(res)
    print(report)
    with open(os.path.join(args.out, "report.txt"), "w") as f:
        f.write(report)
    with open(os.path.join(args.out, "result.json"), "w") as f:
        json.dump(res, f, indent=2)
    with open(os.path.join(args.out, "rfq_nesting.json"), "w") as f:
        json.dump(res["rfq_nesting"], f, indent=2)

    if not args.no_render:
        pdf, pngs = render_layout(res, args.out)
        overview = render_dxf_overview(res, args.out)
        burns = render_burn_dxfs(res, args.out)
        print(f"\nWrote: {pdf}")
        print(f"       {overview}  (overview)")
        for b in burns:
            print(f"       {b}  (burn table — one per sheet)")
        print(f"       {len(pngs)} PNG(s), report.txt, result.json, rfq_nesting.json")


if __name__ == "__main__":
    main()
