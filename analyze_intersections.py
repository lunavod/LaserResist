"""Analyze multi-trace intersections with empty centers."""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from shapely.geometry import Polygon, MultiPolygon, Point
import numpy as np

# Parse the Gerber file
gerber_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Gerber_TopLayer.GTL")
drill_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Drill_PTH_Through.DRL")

print(f"Analyzing {gerber_path.name}...\n")
parser = GerberParser(gerber_path, drill_path)
geometry = parser.parse()

# Normalize to list of polygons
polygons = []
if isinstance(geometry, Polygon):
    polygons = [geometry]
elif isinstance(geometry, MultiPolygon):
    polygons = list(geometry.geoms)

print(f"Total polygons: {len(polygons)}")

# Find polygons with holes (potential multi-trace intersections)
polygons_with_holes = []
for i, poly in enumerate(polygons):
    if len(poly.interiors) > 0:
        polygons_with_holes.append((i, poly))

print(f"Polygons with holes: {len(polygons_with_holes)}")

# Analyze each polygon with holes
print("\nAnalyzing polygons with holes (potential intersection issues):\n")
print("=" * 80)

problematic = []
for idx, (poly_idx, poly) in enumerate(polygons_with_holes):
    area = poly.area
    bounds = poly.bounds
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    num_holes = len(poly.interiors)

    # Calculate hole areas
    hole_areas = []
    for interior in poly.interiors:
        hole_poly = Polygon(interior.coords)
        hole_areas.append(hole_poly.area)

    total_hole_area = sum(hole_areas)

    # Identify potentially problematic polygons:
    # - Small to medium size (not large pads)
    # - Has holes
    # - Hole area is significant relative to total area
    is_small_to_medium = area < 10.0  # Less than 10 mm²
    hole_ratio = total_hole_area / (area + total_hole_area) if (area + total_hole_area) > 0 else 0
    is_significant_hole = hole_ratio > 0.15  # Hole is more than 15% of total

    # Show all polygons with holes for now
    if True:  # is_small_to_medium and is_significant_hole:
        problematic.append((poly_idx, poly))
        print(f"Polygon #{poly_idx} (potential intersection issue):")
        print(f"  Position: ({bounds[0]:.2f}, {bounds[1]:.2f}) to ({bounds[2]:.2f}, {bounds[3]:.2f})")
        print(f"  Size: {width:.2f} x {height:.2f} mm")
        print(f"  Area: {area:.4f} mm² (net), {area + total_hole_area:.4f} mm² (gross)")
        print(f"  Holes: {num_holes}, total hole area: {total_hole_area:.4f} mm²")
        print(f"  Hole ratio: {hole_ratio * 100:.1f}%")

        # Estimate if this could be a trace intersection
        aspect_ratio = max(width, height) / (min(width, height) + 0.001)
        if aspect_ratio < 2.0:  # Roughly square/circular
            print(f"  ⚠ Likely a multi-trace intersection (aspect ratio: {aspect_ratio:.2f})")
        else:
            print(f"  Possibly a trace with hole (aspect ratio: {aspect_ratio:.2f})")

        print()

print("=" * 80)
print(f"\nFound {len(problematic)} potentially problematic polygons")

if problematic:
    print("\nRecommendation:")
    print("These polygons with holes at trace intersections may have unfilled centers.")
    print("Solution: Add centerlines or small circular fill patterns for these areas.")
