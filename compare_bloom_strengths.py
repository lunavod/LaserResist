"""Compare different bloom strength parameters side by side."""

import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator
from test_blooming_fast import FastBloomSimulator

# Increase laser power for better visibility
LASER_POWER_MULTIPLIER = 20.0  # Make laser 20x brighter for visualization

# Parse and generate fills once
gerber_folder = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13")
copper_file = gerber_folder / "Gerber_TopLayer.GTL"

print("Parsing Gerber and generating fills...")
parser = GerberParser(copper_file)
geometry = parser.parse()
trace_centerlines = parser.get_trace_centerlines()
pads = parser.get_pads()

fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)
paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines, pads=pads)

bounds = geometry.bounds

# Test three different bloom strengths
configs = [
    {"name": "Weak (5% scatter)", "scatter_frac": 0.05, "scatter_sigma": 0.8},
    {"name": "Medium (35% scatter)", "scatter_frac": 0.35, "scatter_sigma": 2.0},
    {"name": "Strong (50% scatter)", "scatter_frac": 0.50, "scatter_sigma": 3.0},
]

grids = []
print("\nRunning simulations...")
for cfg in configs:
    print(f"\n{cfg['name']}...")
    sim = FastBloomSimulator(
        resolution=0.05,
        laser_spot_sigma=0.05,
        bloom_scatter_sigma=cfg['scatter_sigma'],
        scatter_fraction=cfg['scatter_frac']
    )
    sim.create_grid(bounds)
    sim.simulate(paths, sample_distance=0.05, min_samples=10)

    # Boost laser power for better visualization
    sim.grid *= LASER_POWER_MULTIPLIER

    grids.append((cfg['name'], sim))

# Find global min/max for consistent color scale
# Use 95th percentile for max to show more color variation
all_values = np.concatenate([sim.grid.flatten() for _, sim in grids])
global_min = 0.0
global_max = np.percentile(all_values[all_values > 0], 95)  # 95th percentile of non-zero values

print(f"\nGlobal energy range: {global_min:.2f} to {global_max:.2f} (95th percentile)")
print(f"Actual max: {all_values.max():.2f}")

# Create comparison visualization
fig, axes = plt.subplots(1, 3, figsize=(24, 8))

colors = ['#000033', '#0000FF', '#00FFFF', '#FFFF00', '#FF0000']
cmap = LinearSegmentedColormap.from_list('bloom', colors, N=256)

for ax, (name, sim) in zip(axes, grids):
    ax.set_title(name, fontsize=14, fontweight='bold')
    ax.set_aspect('equal')
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')

    min_x, min_y, max_x, max_y = sim.bounds

    # Plot with SAME color scale for all
    im = ax.imshow(sim.grid, cmap=cmap, origin='lower',
                   extent=[min_x, max_x, min_y, max_y],
                   interpolation='nearest', aspect='equal',
                   vmin=global_min, vmax=global_max)  # Fixed scale!

    # Add stats
    stats = f"Max: {sim.grid.max():.2f}\nMean: {sim.grid.mean():.2f}"
    ax.text(0.02, 0.98, stats, transform=ax.transAxes,
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat'),
            fontsize=10, family='monospace')

# Single colorbar for all plots
fig.colorbar(im, ax=axes, label='Bloom Energy (same scale for all)',
             orientation='horizontal', pad=0.05, aspect=30)

plt.tight_layout()
plt.savefig('bloom_comparison.png', dpi=250)
print("\nSaved: bloom_comparison.png")
