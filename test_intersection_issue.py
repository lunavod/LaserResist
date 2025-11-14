"""Test script to visualize multi-trace intersection issue."""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPLPolygon
from shapely.geometry import Polygon, MultiPolygon
import numpy as np

# Parse the Gerber file
gerber_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Gerber_TopLayer.GTL")
drill_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Drill_PTH_Through.DRL")

print(f"Parsing {gerber_path.name}...")
parser = GerberParser(gerber_path, drill_path)
geometry = parser.parse()
bounds = parser.get_bounds()
trace_centerlines = parser.get_trace_centerlines()
pads = parser.get_pads()
drill_holes = parser.get_drill_holes()

print(f"Bounds: {bounds}")
print(f"Trace centerlines: {len(trace_centerlines)}")
print(f"Pads: {len(pads)}")

# Generate fill paths
print("\nGenerating fill paths...")
fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)
paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines, offset_centerlines=False, pads=pads, drill_holes=drill_holes)

print(f"Generated {len(paths)} paths")

# Visualize
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
fig.patch.set_facecolor('#2a2a2a')

for ax in [ax1, ax2]:
    ax.set_facecolor('#1a1a1a')
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.2, color='gray', linestyle='--')
    ax.tick_params(colors='white')

    # Plot copper geometry
    polygons = []
    if isinstance(geometry, Polygon):
        polygons = [geometry]
    elif isinstance(geometry, MultiPolygon):
        polygons = list(geometry.geoms)

    for poly in polygons:
        if poly.is_empty:
            continue
        exterior_coords = np.array(poly.exterior.coords)
        patch = MPLPolygon(exterior_coords, closed=True,
                         facecolor='#FFD700', edgecolor='#B8860B',
                         linewidth=0.5, alpha=0.7, zorder=1)
        ax.add_patch(patch)

        # Plot holes
        for interior in poly.interiors:
            interior_coords = np.array(interior.coords)
            hole_patch = MPLPolygon(interior_coords, closed=True,
                                   facecolor='#1a1a1a', edgecolor='#B8860B',
                                   linewidth=0.5, zorder=2)
            ax.add_patch(hole_patch)

# Left plot: show trace centerlines
ax1.set_title('Copper with Trace Centerlines', color='#4CAF50', fontsize=12, fontweight='bold')
for line in trace_centerlines:
    coords = np.array(line.coords)
    if len(coords) >= 2:
        ax1.plot(coords[:, 0], coords[:, 1], color='#FF00FF', linewidth=1.5, alpha=0.8, zorder=3)

# Right plot: show fill paths
ax2.set_title('Fill Paths Generated', color='#4CAF50', fontsize=12, fontweight='bold')
for path in paths:
    coords = np.array(path.coords)
    if len(coords) >= 2:
        ax2.plot(coords[:, 0], coords[:, 1], color='#00FF00', linewidth=0.5, alpha=0.6, zorder=3)

# Set bounds
min_x, min_y, max_x, max_y = bounds
margin = max(max_x - min_x, max_y - min_y) * 0.05
for ax in [ax1, ax2]:
    ax.set_xlim(min_x - margin, max_x + margin)
    ax.set_ylim(min_y - margin, max_y + margin)
    ax.set_xlabel('X (mm)', color='white')
    ax.set_ylabel('Y (mm)', color='white')

plt.tight_layout()
plt.savefig('intersection_issue.png', dpi=150, facecolor='#2a2a2a')
print(f"\n✓ Visualization saved to intersection_issue.png")
plt.close()
