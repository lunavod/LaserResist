"""Visualize junction polygon detection and fills."""

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

# Create fill generator and detect junctions
fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)

# Normalize geometry
if isinstance(geometry, Polygon):
    geom_multi = MultiPolygon([geometry])
else:
    geom_multi = geometry

# Detect junction fills
junction_fills = fill_gen._detect_and_fill_junction_polygons(geom_multi)

print(f"\nDetected {len(junction_fills)} junction fill paths")

# Generate complete fill paths
paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines, offset_centerlines=False, pads=pads, drill_holes=drill_holes)

# Visualize
fig, ax = plt.subplots(figsize=(14, 10))
fig.patch.set_facecolor('#2a2a2a')
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
                     linewidth=0.5, alpha=0.5, zorder=1)
    ax.add_patch(patch)

    # Plot holes
    for interior in poly.interiors:
        interior_coords = np.array(interior.coords)
        hole_patch = MPLPolygon(interior_coords, closed=True,
                               facecolor='#1a1a1a', edgecolor='#B8860B',
                               linewidth=0.5, zorder=2)
        ax.add_patch(hole_patch)

# Plot all fill paths in green
for path in paths:
    coords = np.array(path.coords)
    if len(coords) >= 2:
        ax.plot(coords[:, 0], coords[:, 1], color='#00FF00', linewidth=0.5, alpha=0.3, zorder=3)

# Highlight junction fills in bright magenta
for path in junction_fills:
    coords = np.array(path.coords)
    if len(coords) >= 2:
        ax.plot(coords[:, 0], coords[:, 1], color='#FF00FF', linewidth=2.0, alpha=1.0, zorder=5)

ax.set_title(f'Junction Polygon Fills (Magenta) - {len(junction_fills)} junctions detected',
            color='#FF00FF', fontsize=14, fontweight='bold', pad=20)

# Set bounds
min_x, min_y, max_x, max_y = bounds
margin = max(max_x - min_x, max_y - min_y) * 0.05
ax.set_xlim(min_x - margin, max_x + margin)
ax.set_ylim(min_y - margin, max_y + margin)
ax.set_xlabel('X (mm)', color='white')
ax.set_ylabel('Y (mm)', color='white')

# Add legend
from matplotlib.patches import Patch
legend_elements = [
    Patch(facecolor='#FFD700', edgecolor='#B8860B', alpha=0.5, label='Copper Geometry'),
    Patch(facecolor='#00FF00', edgecolor='#00FF00', alpha=0.3, label='All Fill Paths'),
    Patch(facecolor='#FF00FF', edgecolor='#FF00FF', label='Junction Fills (NEW)'),
]
ax.legend(handles=legend_elements, loc='upper right',
          facecolor='#2a2a2a', edgecolor='#4a4a4a',
          labelcolor='white', framealpha=0.95)

plt.tight_layout()
plt.savefig('junction_fills_visualization.png', dpi=150, facecolor='#2a2a2a')
print(f"\n✓ Visualization saved to junction_fills_visualization.png")
plt.close()
