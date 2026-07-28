import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import ezdxf


ROOT = Path(__file__).resolve().parents[1]
NEST_SCRIPT = ROOT / "skills" / "steel-nest" / "scripts" / "nest.py"
SPEC = importlib.util.spec_from_file_location("pi_steel_nest", NEST_SCRIPT)
nest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = nest
SPEC.loader.exec_module(nest)


def job_with(part, *, stock_qty=1):
    return {
        "job_name": "SYNTHETIC-BURN-GUARD",
        "material": "carbon_steel",
        "grade": "A36",
        "unit_system": "imperial",
        "settings": {
            "kerf_in": 0.06,
            "part_gap_in": 0.25,
            "edge_margin_in": 0.5,
            "density_lb_in3": 0.2836,
            "thickness_in": 0.5,
        },
        "stock": [
            {
                "name": "A36 Plate 1/2",
                "width": 20,
                "height": 20,
                "thickness": 0.5,
                "qty": stock_qty,
            }
        ],
        "parts": [part],
    }


class BurnDxfGuardTests(unittest.TestCase):
    def render_burns(self, job):
        result = nest.run_job(job)
        output_dir = tempfile.TemporaryDirectory()
        self.addCleanup(output_dir.cleanup)
        paths = nest.render_burn_dxfs(result, output_dir.name)
        return result, [Path(path) for path in paths]

    def test_complete_rectangular_part_emits_closed_profile(self):
        result, paths = self.render_burns(
            job_with(
                {
                    "name": "Base Plate",
                    "width": 8,
                    "height": 6,
                    "qty": 1,
                    "shape": "rect",
                    "holes": [{"dia": 1, "x": 4, "y": 3}],
                }
            )
        )

        self.assertEqual(result["unplaced"], [])
        self.assertTrue(result["burn_dxf_eligible"])
        self.assertEqual(result["burn_dxf_warnings"], [])
        self.assertEqual(len(paths), 1)
        document = ezdxf.readfile(paths[0])
        profiles = list(document.modelspace().query('*[layer=="PROFILE"]'))
        holes = list(document.modelspace().query('*[layer=="HOLES"]'))
        self.assertEqual(len(profiles), 1)
        self.assertTrue(profiles[0].closed)
        self.assertEqual(len(holes), 1)

    def test_irregular_part_suppresses_all_burn_dxfs(self):
        result, paths = self.render_burns(
            job_with(
                {
                    "name": "Gusset",
                    "width": 8,
                    "height": 6,
                    "qty": 1,
                    "shape": "irregular",
                    "area": 24,
                }
            )
        )

        self.assertEqual(paths, [])
        self.assertFalse(result["burn_dxf_eligible"])
        self.assertTrue(
            any("irregular" in warning.lower() for warning in result["burn_dxf_warnings"])
        )
        self.assertIn("BURN DXF SUPPRESSED", nest.render_text(result))

        output_dir = tempfile.TemporaryDirectory()
        self.addCleanup(output_dir.cleanup)
        reference_path = Path(nest.render_dxf_overview(result, output_dir.name))
        self.assertEqual(reference_path.name, "reference_nest.dxf")
        self.assertTrue(reference_path.exists())

    def test_unplaced_part_suppresses_burn_dxfs_for_the_whole_job(self):
        job = job_with(
            {
                "name": "Fitting Part",
                "width": 8,
                "height": 6,
                "qty": 1,
                "shape": "rect",
            }
        )
        job["parts"].append(
            {
                "name": "Oversize Part",
                "width": 30,
                "height": 30,
                "qty": 1,
                "shape": "rect",
            }
        )

        result, paths = self.render_burns(job)

        self.assertEqual(paths, [])
        self.assertFalse(result["burn_dxf_eligible"])
        self.assertEqual(len(result["unplaced"]), 1)
        self.assertTrue(
            any("did not fit" in warning.lower() for warning in result["burn_dxf_warnings"])
        )

    def test_hole_outside_part_suppresses_burn_dxfs(self):
        result, paths = self.render_burns(
            job_with(
                {
                    "name": "Plate With Invalid Hole",
                    "width": 8,
                    "height": 6,
                    "qty": 1,
                    "shape": "rect",
                    "holes": [{"dia": 2, "x": 0.5, "y": 3}],
                }
            )
        )

        self.assertEqual(paths, [])
        self.assertFalse(result["burn_dxf_eligible"])
        self.assertTrue(
            any("outside" in warning.lower() for warning in result["burn_dxf_warnings"])
        )


if __name__ == "__main__":
    unittest.main()
