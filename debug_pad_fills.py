"""Debug script to see what fills are being generated for pads."""

import sys
from pathlib import Path
import matplotlib.pyplot as plt
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator

gerber_folder = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13")
copper_file = gerber_folder / "Gerber_TopLayer.GTL"

print("Parsing Gerber...")
parser = GerberParser(copper_file)
geometry = parser.parse()
trace_centerlines = parser.get_trace_centerlines()
pads = parser.get_pads()
drill_holes = parser.get_drill_holes()

print(f"\nFound {len(pads)} pads:")
for i, pad in enumerate(pads[:10]):  # Show first 10
    print(f"  Pad {i}: {pad['aperture_type']}, size={pad.get('size', 'N/A')}, area={pad['geometry'].area:.3f}mm²")

print(f"\nDrill holes: {drill_holes is not None}")
if drill_holes:
    print(f"  Drill hole area: {drill_holes.area:.2f}mm²")

print("\n\nGenerating fills WITHOUT drill holes...")
fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)
paths_no_drill = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines, pads=pads, drill_holes=None)

print("\n\nGenerating fills WITH drill holes...")
fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)
paths_with_drill = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines, pads=pads, drill_holes=drill_holes)

print(f"\n\nResults:")
print(f"  Paths without drill holes: {len(paths_no_drill)}")
print(f"  Paths with drill holes: {len(paths_with_drill)}")
print(f"  Difference: {len(paths_no_drill) - len(paths_with_drill)} paths lost to drill holes")

# Let's visualize a specific pad area to see the fills
fig, axes = plt.subplots(1, 3, figsize=(18, 6))

# Pick a pad to examine (one of the circular pads around x=50, y=27)
focus_area = (48, 25, 52, 29)  # x_min, y_min, x_max, y_max

for ax, paths, title in zip(axes,
                             [paths_no_drill, paths_with_drill, paths_with_drill],
                             ['Without Drill Holes', 'With Drill Holes', 'Path Density']):
    ax.set_title(title, fontweight='bold')
    ax.set_aspect('equal')
    ax.set_xlim(focus_area[0], focus_area[2])
    ax.set_ylim(focus_area[1], focus_area[3])
    ax.grid(True, alpha=0.3)

    # Draw paths in this area
    path_count = 0
    for path in paths:
        # Check if path intersects focus area
        if path.intersects(box(*focus_area)):
            coords = list(path.coords)
            xs, ys = zip(*coords)
            ax.plot(xs, ys, 'b-', linewidth=1, alpha=0.7)
            path_count += 1

    # Draw geometry outline
    for geom in geometry.geoms if hasattr(geometry, 'geoms') else [geometry]:
        if geom.intersects(box(*focus_area)):
            x, y = geom.exterior.xy
            ax.plot(x, y, 'gray', linewidth=0.5, alpha=0.5)

    # Draw drill holes if applicable
    if title == 'With Drill Holes' and drill_holes:
        for hole in drill_holes.geoms if hasattr(drill_holes, 'geoms') else [drill_holes]:
            if hole.intersects(box(*focus_area)):
                x, y = hole.exterior.xy
                ax.fill(x, y, 'red', alpha=0.3)
                ax.plot(x, y, 'red', linewidth=1)

    ax.text(0.02, 0.98, f'{path_count} paths', transform=ax.transAxes,
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat'))

plt.tight_layout()
plt.savefig('pad_fill_debug.png', dpi=200)
print("\n\nSaved visualization to pad_fill_debug.png")

# Count paths that are very short (might be pad contours)
short_paths = [p for p in paths_with_drill if p.length < 5.0]  # < 5mm
medium_paths = [p for p in paths_with_drill if 5.0 <= p.length < 20.0]
long_paths = [p for p in paths_with_drill if p.length >= 20.0]

print(f"\n\nPath length distribution:")
print(f"  Short (<5mm): {len(short_paths)} paths - likely pad contours")
print(f"  Medium (5-20mm): {len(medium_paths)} paths")
print(f"  Long (>20mm): {len(long_paths)} paths - likely trace centerlines")
