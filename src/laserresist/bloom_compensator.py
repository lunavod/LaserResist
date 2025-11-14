"""Bloom compensation using trace-based ambient exposure analysis."""

import numpy as np
from shapely.geometry import LineString
from scipy.ndimage import gaussian_filter
from typing import List, Tuple
import time


class FastBloomSimulator:
    """Fast blooming simulation using rasterization + convolution."""

    def __init__(self, resolution=0.05, laser_spot_sigma=0.05, bloom_scatter_sigma=2.0,
                 scatter_fraction=0.35):
        """
        Args:
            resolution: Grid resolution in mm
            laser_spot_sigma: Sigma for tight laser spot Gaussian (mm)
            bloom_scatter_sigma: Sigma for bloom scatter Gaussian (mm)
            scatter_fraction: Fraction of energy that goes into scatter (rest is tight spot)
        """
        self.resolution = resolution
        self.laser_spot_sigma = laser_spot_sigma
        self.bloom_scatter_sigma = bloom_scatter_sigma
        self.scatter_fraction = scatter_fraction
        self.grid = None
        self.bounds = None
        self.grid_shape = None

    def create_grid(self, bounds):
        """Create the energy grid."""
        min_x, min_y, max_x, max_y = bounds

        # Add padding for bloom
        padding = max(self.bloom_scatter_sigma * 3, 2.0)  # 3-sigma or 2mm
        min_x -= padding
        min_y -= padding
        max_x += padding
        max_y += padding

        self.bounds = (min_x, min_y, max_x, max_y)

        width = max_x - min_x
        height = max_y - min_y

        grid_width = int(np.ceil(width / self.resolution))
        grid_height = int(np.ceil(height / self.resolution))

        self.grid_shape = (grid_height, grid_width)
        self.grid = np.zeros(self.grid_shape, dtype=np.float32)

    def world_to_grid(self, x, y):
        """Convert world coordinates to grid indices."""
        min_x, min_y, _, _ = self.bounds
        grid_x = int(np.round((x - min_x) / self.resolution))
        grid_y = int(np.round((y - min_y) / self.resolution))
        return grid_x, grid_y

    def rasterize_paths(self, paths, sample_distance=0.05, min_samples=10):
        """Rasterize all laser paths onto the grid."""
        raster_grid = np.zeros(self.grid_shape, dtype=np.float32)

        for path in paths:
            # Sample points along path
            length = path.length
            num_samples_by_length = max(2, int(np.ceil(length / sample_distance)))
            num_samples = max(num_samples_by_length, min_samples)

            if num_samples == 2:
                coords = list(path.coords)
            else:
                coords = [path.interpolate(i / (num_samples - 1), normalized=True).coords[0]
                         for i in range(num_samples)]

            # Mark grid cells where laser hits
            for x, y in coords:
                gx, gy = self.world_to_grid(x, y)
                if 0 <= gx < self.grid_shape[1] and 0 <= gy < self.grid_shape[0]:
                    raster_grid[gy, gx] += 1.0  # Accumulate hits

        return raster_grid

    def apply_bloom_convolution(self, raster_grid):
        """Apply bloom using Gaussian convolution."""
        # Convert sigmas from mm to grid cells
        spot_sigma_cells = self.laser_spot_sigma / self.resolution
        scatter_sigma_cells = self.bloom_scatter_sigma / self.resolution

        # Apply tight laser spot Gaussian
        primary_energy = gaussian_filter(raster_grid, sigma=spot_sigma_cells, mode='constant')

        # Apply bloom scatter Gaussian
        scatter_energy = gaussian_filter(raster_grid, sigma=scatter_sigma_cells, mode='constant')

        # Combine: most energy in tight spot, little in scatter
        primary_fraction = 1.0 - self.scatter_fraction
        bloom_grid = primary_fraction * primary_energy + self.scatter_fraction * scatter_energy

        return bloom_grid

    def simulate(self, paths, sample_distance=0.05, min_samples=10):
        """Run complete simulation: rasterize + convolve."""
        # Rasterize paths
        raster_grid = self.rasterize_paths(paths, sample_distance, min_samples)

        # Apply bloom via convolution
        self.grid = self.apply_bloom_convolution(raster_grid)

        return self.grid

    def get_path_ambient_bloom(self, path, sample_radius_mm=1.5, num_samples=20):
        """Get average AMBIENT bloom AROUND a path (not on it).

        This measures bloom energy in the vicinity, indicating how much
        ambient exposure the path gets from nearby copper.
        """
        energies = []
        radius_cells = max(1, int(sample_radius_mm / self.resolution))

        for i in range(num_samples):
            point = path.interpolate(i / (num_samples - 1), normalized=True)
            x, y = point.x, point.y
            center_gx, center_gy = self.world_to_grid(x, y)

            # Sample a ring around this point (excluding center)
            ring_energies = []
            for dx in range(-radius_cells, radius_cells + 1):
                for dy in range(-radius_cells, radius_cells + 1):
                    # Skip center - we want ambient, not direct exposure
                    if abs(dx) <= 1 and abs(dy) <= 1:
                        continue

                    dist = np.sqrt(dx**2 + dy**2)
                    if dist <= radius_cells:
                        gx = center_gx + dx
                        gy = center_gy + dy
                        if 0 <= gx < self.grid_shape[1] and 0 <= gy < self.grid_shape[0]:
                            ring_energies.append(self.grid[gy, gx])

            if ring_energies:
                energies.append(np.mean(ring_energies))

        return np.mean(energies) if energies else 0.0


def identify_underexposed_traces(simulator, trace_elements, threshold_percentile=30,
                                  min_trace_length=0.2, verbose=False):
    """Identify under-exposed traces based on ambient bloom.

    Args:
        simulator: FastBloomSimulator with simulated bloom grid
        trace_elements: List of trace dicts from GerberParser.get_trace_centerlines()
        threshold_percentile: Percentile threshold for under-exposure classification
        min_trace_length: Minimum trace length to analyze (mm)
        verbose: Print detailed statistics

    Returns:
        Tuple of (normal_traces, underexposed_traces) where each is a list of trace dicts
    """
    # Filter traces by length
    meaningful_traces = [t for t in trace_elements if t['line'].length >= min_trace_length]

    if verbose:
        print(f"  Analyzing {len(meaningful_traces)} traces (>= {min_trace_length}mm)")

    # Analyze ambient bloom at each trace
    trace_bloom_data = []
    for trace_info in meaningful_traces:
        line = trace_info['line']
        ambient_bloom = simulator.get_path_ambient_bloom(line, sample_radius_mm=1.5, num_samples=20)
        trace_bloom_data.append({
            'trace_info': trace_info,
            'ambient_bloom': ambient_bloom
        })

    # Calculate threshold
    bloom_values = np.array([t['ambient_bloom'] for t in trace_bloom_data])
    bloom_threshold = np.percentile(bloom_values, threshold_percentile)

    if verbose:
        print(f"  Ambient bloom: min={bloom_values.min():.2f}, max={bloom_values.max():.2f}, "
              f"mean={bloom_values.mean():.2f}, {threshold_percentile}th%={bloom_threshold:.2f}")

    # Classify traces
    normal_traces = []
    underexposed_traces = []

    for trace_data in trace_bloom_data:
        if trace_data['ambient_bloom'] < bloom_threshold:
            underexposed_traces.append(trace_data['trace_info'])
        else:
            normal_traces.append(trace_data['trace_info'])

    return normal_traces, underexposed_traces


def generate_compensation_paths(underexposed_traces, fill_generator):
    """Generate additional fill paths for under-exposed traces.

    Args:
        underexposed_traces: List of trace dicts that need compensation
        fill_generator: FillGenerator instance to use

    Returns:
        List of LineString paths for additional exposure
    """
    additional_paths = []

    for trace_info in underexposed_traces:
        trace_line = trace_info['line']
        trace_width = trace_info['width']

        # Reconstruct the trace geometry (buffered line)
        trace_geom = trace_line.buffer(trace_width / 2, cap_style='round', join_style='round')

        # Generate fills for ONLY this trace (no trace_centerlines, no pads)
        trace_fills = fill_generator.generate_fill(trace_geom, trace_centerlines=[], pads=[])
        additional_paths.extend(trace_fills)

    return additional_paths


def generate_debug_visualization(simulator, geometry, normal_traces, underexposed_traces,
                                 compensation_paths, output_path, verbose=False):
    """Generate debug visualization of bloom compensation.

    Args:
        simulator: FastBloomSimulator with completed simulation
        geometry: Full board geometry (Polygon or MultiPolygon)
        normal_traces: List of normal trace dicts
        underexposed_traces: List of under-exposed trace dicts
        compensation_paths: List of compensation LineString paths
        output_path: Path to save the PNG image
        verbose: Print progress messages

    Returns:
        True if visualization was generated, False if matplotlib unavailable
    """
    try:
        import matplotlib.pyplot as plt
        from matplotlib.colors import LinearSegmentedColormap
        from shapely.geometry import Polygon, MultiPolygon
    except ImportError:
        if verbose:
            print("  Warning: matplotlib not available, skipping visualization")
        return False

    if verbose:
        print(f"  Generating bloom visualization...")

    # Create figure with 3 panels
    fig, axes = plt.subplots(1, 3, figsize=(24, 8))

    # Custom colormap for bloom
    colors = ['#000033', '#0000FF', '#00FFFF', '#FFFF00', '#FF0000']
    cmap = LinearSegmentedColormap.from_list('bloom', colors, N=256)

    # Use 95th percentile for color scale
    vmax = np.percentile(simulator.grid[simulator.grid > 0], 95) if np.any(simulator.grid > 0) else 1.0
    min_x, min_y, max_x, max_y = simulator.bounds

    # Panel 1: Bloom heatmap
    ax1 = axes[0]
    ax1.set_title('Ambient Bloom Simulation\n(from normal fills)', fontsize=14, fontweight='bold')
    ax1.set_aspect('equal')
    ax1.set_xlabel('X (mm)')
    ax1.set_ylabel('Y (mm)')

    im = ax1.imshow(simulator.grid, cmap=cmap, origin='lower',
                    extent=[min_x, max_x, min_y, max_y],
                    interpolation='nearest', aspect='equal',
                    vmin=0, vmax=vmax)

    cbar = plt.colorbar(im, ax=ax1, fraction=0.046, pad=0.04)
    cbar.set_label('Ambient Energy', rotation=270, labelpad=15)

    # Panel 2: Source traces colored by exposure
    ax2 = axes[1]
    ax2.set_title('Source Trace Elements\n(colored by ambient bloom)', fontsize=14, fontweight='bold')
    ax2.set_aspect('equal')
    ax2.grid(True, alpha=0.3)
    ax2.set_xlabel('X (mm)')
    ax2.set_ylabel('Y (mm)')

    # Draw copper geometry
    if isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            x, y = poly.exterior.xy
            ax2.fill(x, y, color='lightgray', alpha=0.2, edgecolor='black', linewidth=0.3)
    elif isinstance(geometry, Polygon):
        x, y = geometry.exterior.xy
        ax2.fill(x, y, color='lightgray', alpha=0.2, edgecolor='black', linewidth=0.3)

    # Draw normal traces
    for i, trace_info in enumerate(normal_traces):
        coords = list(trace_info['line'].coords)
        xs, ys = zip(*coords)
        label = 'Normal exposure' if i == 0 else ''
        ax2.plot(xs, ys, color='blue', linewidth=1.5, alpha=0.7, label=label)

    # Draw under-exposed traces
    for i, trace_info in enumerate(underexposed_traces):
        coords = list(trace_info['line'].coords)
        xs, ys = zip(*coords)
        label = 'Under-exposed' if i == 0 else ''
        ax2.plot(xs, ys, color='red', linewidth=2.0, alpha=0.9, label=label)

    if normal_traces or underexposed_traces:
        ax2.legend(loc='upper right', fontsize=10)

    # Calculate stats
    normal_length = sum(t['line'].length for t in normal_traces)
    under_length = sum(t['line'].length for t in underexposed_traces)
    total_length = normal_length + under_length

    stats_text = f"Source Traces:\n"
    stats_text += f"Normal: {len(normal_traces)} ({normal_length:.1f}mm)\n"
    stats_text += f"Under-exposed: {len(underexposed_traces)} ({under_length:.1f}mm)\n"
    if total_length > 0:
        stats_text += f"Under-exposed %: {under_length / total_length * 100:.1f}%"

    ax2.text(0.02, 0.98, stats_text, transform=ax2.transAxes,
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
             fontsize=9, family='monospace')

    # Panel 3: Compensation paths
    ax3 = axes[2]
    ax3.set_title('Additional Fill Paths\n(for under-exposed traces only)', fontsize=14, fontweight='bold')
    ax3.set_aspect('equal')
    ax3.grid(True, alpha=0.3)
    ax3.set_xlabel('X (mm)')
    ax3.set_ylabel('Y (mm)')

    # Draw copper geometry
    if isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            x, y = poly.exterior.xy
            ax3.fill(x, y, color='lightgray', alpha=0.2, edgecolor='black', linewidth=0.3)
    elif isinstance(geometry, Polygon):
        x, y = geometry.exterior.xy
        ax3.fill(x, y, color='lightgray', alpha=0.2, edgecolor='black', linewidth=0.3)

    # Draw under-exposed traces
    for trace_info in underexposed_traces:
        coords = list(trace_info['line'].coords)
        xs, ys = zip(*coords)
        ax3.plot(xs, ys, color='red', linewidth=2.0, alpha=0.5, label='Under-exposed trace')

    # Draw compensation fill paths
    for i, path in enumerate(compensation_paths):
        coords = list(path.coords)
        xs, ys = zip(*coords)
        label = 'Compensation fills (2x)' if i == 0 else ''
        ax3.plot(xs, ys, color='green', linewidth=0.8, alpha=0.6, label=label)

    # Remove duplicate labels
    handles, labels = ax3.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax3.legend(by_label.values(), by_label.keys(), loc='upper right', fontsize=10)

    comp_length = sum(p.length for p in compensation_paths)
    fill_stats = f"Fill Paths:\n"
    fill_stats += f"Compensation paths: {len(compensation_paths)}\n"
    fill_stats += f"Total length: {comp_length:.1f}mm (2x exposure)"

    ax3.text(0.02, 0.98, fill_stats, transform=ax3.transAxes,
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8),
             fontsize=9, family='monospace')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)

    if verbose:
        print(f"  ✓ Saved visualization to: {output_path}")

    return True
