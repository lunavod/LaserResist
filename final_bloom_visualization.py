"""Final blooming visualization with optimal 35% scatter parameters."""

import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator
from test_blooming_fast import FastBloomSimulator

# Parse and generate fills
gerber_folder = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13")
copper_file = gerber_folder / "Gerber_TopLayer.GTL"

print("Parsing Gerber and generating fills...")
parser = GerberParser(copper_file)
geometry = parser.parse()
trace_centerlines = parser.get_trace_centerlines()
pads = parser.get_pads()

fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)
paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines, pads=pads)

print(f"Generated {len(paths)} paths")

# Run simulation with optimal parameters
print("\nRunning blooming simulation (35% scatter, 2.0mm sigma)...")
sim = FastBloomSimulator(
    resolution=0.05,
    laser_spot_sigma=0.05,
    bloom_scatter_sigma=2.0,
    scatter_fraction=0.35
)

bounds = geometry.bounds
sim.create_grid(bounds)
sim.simulate(paths, sample_distance=0.05, min_samples=10)

# Boost for visualization
LASER_POWER = 20.0
sim.grid *= LASER_POWER

# Filter to only analyze TRACES (long, open paths), not pad fill contours or board outline
MIN_TRACE_LENGTH = 5.0  # mm - anything shorter is probably a pad contour

# Separate paths by type
trace_paths = []
filtered_out = {'short': 0, 'closed_loop': 0, 'board_outline': 0}

for p in paths:
    # Skip short paths (pad contours)
    if p.length < MIN_TRACE_LENGTH:
        filtered_out['short'] += 1
        continue

    # Skip closed loops (pad centerlines - start and end are same)
    coords = list(p.coords)
    if len(coords) >= 2:
        start = coords[0]
        end = coords[-1]
        dist = ((start[0]-end[0])**2 + (start[1]-end[1])**2)**0.5
        if dist < 0.1:  # Closed loop
            filtered_out['closed_loop'] += 1
            continue

    # Skip very long paths that are likely board outline (>100mm)
    if p.length > 100:
        filtered_out['board_outline'] += 1
        continue

    trace_paths.append(p)

print(f"\nPath filtering:")
print(f"  Total paths: {len(paths)}")
print(f"  Actual traces: {len(trace_paths)}")
print(f"  Filtered out:")
print(f"    - Short paths (<{MIN_TRACE_LENGTH}mm): {filtered_out['short']}")
print(f"    - Closed loops (pad centerlines): {filtered_out['closed_loop']}")
print(f"    - Board outline (>100mm): {filtered_out['board_outline']}")

# Analyze only trace paths
normal_paths, underexposed_paths, energies = sim.identify_underexposed_paths(trace_paths, threshold_percentile=30)

print(f"\nResults:")
print(f"  Normal traces: {len(normal_paths)}")
print(f"  Under-exposed traces: {len(underexposed_paths)}")

# Create clean visualization
fig, axes = plt.subplots(1, 2, figsize=(18, 8))

colors = ['#000033', '#0000FF', '#00FFFF', '#FFFF00', '#FF0000']
cmap = LinearSegmentedColormap.from_list('bloom', colors, N=256)

# Use 95th percentile for color scale
vmax = np.percentile(sim.grid[sim.grid > 0], 95)

min_x, min_y, max_x, max_y = sim.bounds

# Plot 1: Bloom heatmap
ax1 = axes[0]
ax1.set_title('Blooming Energy Simulation', fontsize=14, fontweight='bold')
ax1.set_aspect('equal')
ax1.set_xlabel('X (mm)')
ax1.set_ylabel('Y (mm)')

im = ax1.imshow(sim.grid, cmap=cmap, origin='lower',
                extent=[min_x, max_x, min_y, max_y],
                interpolation='nearest', aspect='equal',
                vmin=0, vmax=vmax)

# Smaller colorbar on the side
cbar = plt.colorbar(im, ax=ax1, fraction=0.046, pad=0.04)
cbar.set_label('Energy', rotation=270, labelpad=15)

# Plot 2: Under-exposed paths
ax2 = axes[1]
ax2.set_title('Detected Under-Exposed Paths', fontsize=14, fontweight='bold')
ax2.set_aspect('equal')
ax2.grid(True, alpha=0.3)
ax2.set_xlabel('X (mm)')
ax2.set_ylabel('Y (mm)')

# Draw copper geometry
from shapely.geometry import Polygon, MultiPolygon
if isinstance(geometry, MultiPolygon):
    for poly in geometry.geoms:
        x, y = poly.exterior.xy
        ax2.fill(x, y, color='lightgray', alpha=0.3, edgecolor='black', linewidth=0.5)
elif isinstance(geometry, Polygon):
    x, y = geometry.exterior.xy
    ax2.fill(x, y, color='lightgray', alpha=0.3, edgecolor='black', linewidth=0.5)

# Draw normal paths
for i, path in enumerate(normal_paths):
    coords = list(path.coords)
    xs, ys = zip(*coords)
    label = 'Normal exposure' if i == 0 else ''
    ax2.plot(xs, ys, color='blue', linewidth=0.8, alpha=0.6, label=label)

# Draw under-exposed paths
for i, path in enumerate(underexposed_paths):
    coords = list(path.coords)
    xs, ys = zip(*coords)
    label = 'Under-exposed (2x)' if i == 0 else ''
    ax2.plot(xs, ys, color='red', linewidth=1.5, alpha=0.9, label=label)

ax2.legend(loc='upper right', fontsize=10)

# Stats
normal_length = sum(p.length for p in normal_paths)
under_length = sum(p.length for p in underexposed_paths)
stats_text = f"Normal: {len(normal_paths)} paths ({normal_length:.1f}mm)\n"
stats_text += f"Under-exposed: {len(underexposed_paths)} paths ({under_length:.1f}mm)\n"
stats_text += f"Under-exposed: {under_length / (normal_length + under_length) * 100:.1f}%"

ax2.text(0.02, 0.98, stats_text, transform=ax2.transAxes,
         verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
         fontsize=9, family='monospace')

plt.tight_layout()
plt.savefig('bloom_final.png', dpi=300, bbox_inches='tight')
print("\nSaved: bloom_final.png")
