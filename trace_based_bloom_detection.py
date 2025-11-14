"""Trace-based bloom detection - analyzes source Gerber traces, not fill paths."""

import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from shapely.geometry import Polygon, MultiPolygon

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator
from test_blooming_fast import FastBloomSimulator

# Parse Gerber
gerber_folder = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13")
copper_file = gerber_folder / "Gerber_TopLayer.GTL"

print("="*80)
print("TRACE-BASED BLOOM DETECTION")
print("="*80)

print("\n[1/6] Parsing Gerber file...")
parser = GerberParser(copper_file)
full_geometry = parser.parse()  # Merged polygon for entire board
trace_elements = parser.get_trace_centerlines()  # Individual traces!
pads = parser.get_pads()

print(f"  Full geometry bounds: {full_geometry.bounds}")
print(f"  Trace elements: {len(trace_elements)}")
print(f"  Pads: {len(pads)}")

# Filter traces - only keep meaningful ones (filter out noise/artifacts)
MIN_TRACE_LENGTH = 0.2  # mm - very short (probably artifacts or via connections)
meaningful_traces = [t for t in trace_elements if t['line'].length >= MIN_TRACE_LENGTH]
print(f"  Traces >= {MIN_TRACE_LENGTH}mm: {len(meaningful_traces)}")

# 2. Generate normal fills for entire board
print("\n[2/6] Generating normal fills for entire board...")
fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)
normal_paths = fill_gen.generate_fill(full_geometry, trace_centerlines=trace_elements, pads=pads)
print(f"  Generated {len(normal_paths)} normal fill paths")

# 3. Simulate bloom from normal fills
print("\n[3/6] Simulating bloom from normal fills...")
sim = FastBloomSimulator(
    resolution=0.05,
    laser_spot_sigma=0.05,
    bloom_scatter_sigma=2.0,
    scatter_fraction=0.35
)

bounds = full_geometry.bounds
sim.create_grid(bounds)
sim.simulate(normal_paths, sample_distance=0.05, min_samples=10)

# Boost for analysis
LASER_POWER = 20.0
sim.grid *= LASER_POWER

# 4. Analyze ambient bloom at SOURCE TRACES
print("\n[4/6] Analyzing ambient bloom at source trace elements...")
trace_bloom_data = []

for i, trace_info in enumerate(meaningful_traces):
    if (i + 1) % 50 == 0:
        print(f"  Analyzed {i + 1}/{len(meaningful_traces)} traces...")

    line = trace_info['line']
    width = trace_info['width']

    # Measure ambient bloom around this trace
    ambient_bloom = sim.get_path_ambient_bloom(line, sample_radius_mm=1.5, num_samples=20)

    trace_bloom_data.append({
        'trace_info': trace_info,
        'line': line,
        'width': width,
        'length': line.length,
        'ambient_bloom': ambient_bloom
    })

# Calculate statistics
bloom_values = np.array([t['ambient_bloom'] for t in trace_bloom_data])
threshold_percentile = 30
bloom_threshold = np.percentile(bloom_values, threshold_percentile)

print(f"\n  Ambient bloom statistics:")
print(f"    Min: {bloom_values.min():.2f}")
print(f"    Max: {bloom_values.max():.2f}")
print(f"    Mean: {bloom_values.mean():.2f}")
print(f"    Median: {np.median(bloom_values):.2f}")
print(f"    {threshold_percentile}th percentile (threshold): {bloom_threshold:.2f}")

# 5. Identify under-exposed traces and generate additional fills
print(f"\n[5/6] Identifying under-exposed traces...")
normal_traces = []
underexposed_traces = []
additional_paths = []

for trace_data in trace_bloom_data:
    if trace_data['ambient_bloom'] < bloom_threshold:
        underexposed_traces.append(trace_data)

        # Generate additional fills for JUST this trace geometry
        trace_line = trace_data['line']
        trace_width = trace_data['width']

        # Reconstruct the trace geometry (buffered line)
        trace_geom = trace_line.buffer(trace_width / 2, cap_style='round', join_style='round')

        # Generate fills for ONLY this trace (no trace_centerlines, no pads)
        # Use tighter spacing for additional pass
        trace_fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)
        trace_fills = trace_fill_gen.generate_fill(trace_geom, trace_centerlines=[], pads=[])
        additional_paths.extend(trace_fills)
    else:
        normal_traces.append(trace_data)

print(f"  Normal traces: {len(normal_traces)}")
print(f"  Under-exposed traces: {len(underexposed_traces)}")
print(f"  Under-exposed %: {len(underexposed_traces) / len(trace_bloom_data) * 100:.1f}%")
print(f"  Additional fill paths generated: {len(additional_paths)}")

# Calculate total trace lengths
normal_length = sum(t['length'] for t in normal_traces)
under_length = sum(t['length'] for t in underexposed_traces)
total_length = normal_length + under_length

print(f"\n  Trace lengths:")
print(f"    Normal: {normal_length:.1f}mm")
print(f"    Under-exposed: {under_length:.1f}mm")
print(f"    Under-exposed %: {under_length / total_length * 100:.1f}%")

# 6. Visualize results
print("\n[6/6] Creating visualization...")

fig, axes = plt.subplots(1, 3, figsize=(24, 8))

colors = ['#000033', '#0000FF', '#00FFFF', '#FFFF00', '#FF0000']
cmap = LinearSegmentedColormap.from_list('bloom', colors, N=256)

# Use 95th percentile for color scale
vmax = np.percentile(sim.grid[sim.grid > 0], 95)
min_x, min_y, max_x, max_y = sim.bounds

# Plot 1: Bloom heatmap
ax1 = axes[0]
ax1.set_title('Ambient Bloom Simulation\n(from normal fills)', fontsize=14, fontweight='bold')
ax1.set_aspect('equal')
ax1.set_xlabel('X (mm)')
ax1.set_ylabel('Y (mm)')

im = ax1.imshow(sim.grid, cmap=cmap, origin='lower',
                extent=[min_x, max_x, min_y, max_y],
                interpolation='nearest', aspect='equal',
                vmin=0, vmax=vmax)

cbar = plt.colorbar(im, ax=ax1, fraction=0.046, pad=0.04)
cbar.set_label('Ambient Energy', rotation=270, labelpad=15)

# Plot 2: Source traces colored by exposure
ax2 = axes[1]
ax2.set_title('Source Trace Elements\n(colored by ambient bloom)', fontsize=14, fontweight='bold')
ax2.set_aspect('equal')
ax2.grid(True, alpha=0.3)
ax2.set_xlabel('X (mm)')
ax2.set_ylabel('Y (mm)')

# Draw copper geometry
if isinstance(full_geometry, MultiPolygon):
    for poly in full_geometry.geoms:
        x, y = poly.exterior.xy
        ax2.fill(x, y, color='lightgray', alpha=0.2, edgecolor='black', linewidth=0.3)
elif isinstance(full_geometry, Polygon):
    x, y = full_geometry.exterior.xy
    ax2.fill(x, y, color='lightgray', alpha=0.2, edgecolor='black', linewidth=0.3)

# Draw normal traces
for i, trace_data in enumerate(normal_traces):
    coords = list(trace_data['line'].coords)
    xs, ys = zip(*coords)
    label = 'Normal exposure' if i == 0 else ''
    ax2.plot(xs, ys, color='blue', linewidth=1.5, alpha=0.7, label=label)

# Draw under-exposed traces
for i, trace_data in enumerate(underexposed_traces):
    coords = list(trace_data['line'].coords)
    xs, ys = zip(*coords)
    label = 'Under-exposed' if i == 0 else ''
    ax2.plot(xs, ys, color='red', linewidth=2.0, alpha=0.9, label=label)

if normal_traces or underexposed_traces:
    ax2.legend(loc='upper right', fontsize=10)

stats_text = f"Source Traces:\n"
stats_text += f"Normal: {len(normal_traces)} ({normal_length:.1f}mm)\n"
stats_text += f"Under-exposed: {len(underexposed_traces)} ({under_length:.1f}mm)\n"
stats_text += f"Under-exposed %: {under_length / total_length * 100:.1f}%"

ax2.text(0.02, 0.98, stats_text, transform=ax2.transAxes,
         verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
         fontsize=9, family='monospace')

# Plot 3: Additional fill paths for under-exposed traces
ax3 = axes[2]
ax3.set_title('Additional Fill Paths\n(for under-exposed traces only)', fontsize=14, fontweight='bold')
ax3.set_aspect('equal')
ax3.grid(True, alpha=0.3)
ax3.set_xlabel('X (mm)')
ax3.set_ylabel('Y (mm)')

# Draw copper geometry
if isinstance(full_geometry, MultiPolygon):
    for poly in full_geometry.geoms:
        x, y = poly.exterior.xy
        ax3.fill(x, y, color='lightgray', alpha=0.2, edgecolor='black', linewidth=0.3)
elif isinstance(full_geometry, Polygon):
    x, y = full_geometry.exterior.xy
    ax3.fill(x, y, color='lightgray', alpha=0.2, edgecolor='black', linewidth=0.3)

# Draw under-exposed traces
for trace_data in underexposed_traces:
    coords = list(trace_data['line'].coords)
    xs, ys = zip(*coords)
    ax3.plot(xs, ys, color='red', linewidth=2.0, alpha=0.5, label='Under-exposed trace')

# Draw additional fill paths
for i, path in enumerate(additional_paths):
    coords = list(path.coords)
    xs, ys = zip(*coords)
    label = 'Additional fills (2x)' if i == 0 else ''
    ax3.plot(xs, ys, color='green', linewidth=0.8, alpha=0.6, label=label)

# Remove duplicate labels
handles, labels = ax3.get_legend_handles_labels()
by_label = dict(zip(labels, handles))
ax3.legend(by_label.values(), by_label.keys(), loc='upper right', fontsize=10)

fill_stats = f"Fill Paths:\n"
fill_stats += f"Normal fills: {len(normal_paths)}\n"
fill_stats += f"Additional fills: {len(additional_paths)}\n"
fill_stats += f"Total: {len(normal_paths) + len(additional_paths)}\n"
fill_stats += f"Increase: +{len(additional_paths) / len(normal_paths) * 100:.1f}%"

ax3.text(0.02, 0.98, fill_stats, transform=ax3.transAxes,
         verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8),
         fontsize=9, family='monospace')

plt.tight_layout()
output_file = 'trace_based_bloom_detection.png'
plt.savefig(output_file, dpi=300, bbox_inches='tight')
print(f"\nSaved: {output_file}")

print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"Analyzed {len(meaningful_traces)} source traces")
print(f"Identified {len(underexposed_traces)} under-exposed traces ({under_length / total_length * 100:.1f}%)")
print(f"Generated {len(additional_paths)} additional fill paths")
print(f"Total paths: {len(normal_paths)} + {len(additional_paths)} = {len(normal_paths) + len(additional_paths)}")
print("="*80)
