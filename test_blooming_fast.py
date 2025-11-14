"""Fast blooming simulation using convolution with proper laser physics."""

import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from shapely.geometry import LineString, Polygon, MultiPolygon
from scipy.ndimage import gaussian_filter
import time

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator


class FastBloomSimulator:
    """Fast blooming simulation using rasterization + convolution."""

    def __init__(self, resolution=0.05, laser_spot_sigma=0.05, bloom_scatter_sigma=0.8,
                 scatter_fraction=0.05):
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

        print(f"  Grid: {grid_width} x {grid_height} = {grid_width * grid_height:,} cells")
        print(f"  Bounds: ({min_x:.1f}, {min_y:.1f}) to ({max_x:.1f}, {max_y:.1f}) mm")

    def world_to_grid(self, x, y):
        """Convert world coordinates to grid indices."""
        min_x, min_y, _, _ = self.bounds
        grid_x = int(np.round((x - min_x) / self.resolution))
        grid_y = int(np.round((y - min_y) / self.resolution))
        return grid_x, grid_y

    def grid_to_world(self, grid_x, grid_y):
        """Convert grid indices to world coordinates."""
        min_x, min_y, _, _ = self.bounds
        x = min_x + grid_x * self.resolution
        y = min_y + grid_y * self.resolution
        return x, y

    def rasterize_paths(self, paths, sample_distance=0.05, min_samples=10):
        """Rasterize all laser paths onto the grid.

        Args:
            paths: List of LineString paths
            sample_distance: Sample spacing along paths
            min_samples: Minimum samples per path

        Returns:
            Binary grid with 1 where laser hits, 0 elsewhere
        """
        print(f"\n  Rasterizing {len(paths)} paths...")
        start_time = time.time()

        raster_grid = np.zeros(self.grid_shape, dtype=np.float32)

        for i, path in enumerate(paths):
            if (i + 1) % 100 == 0:
                print(f"    Rasterized {i + 1}/{len(paths)} paths...")

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

        elapsed = time.time() - start_time
        print(f"  Rasterization completed in {elapsed:.2f}s")
        print(f"  Grid cells with laser hits: {np.sum(raster_grid > 0):,}")

        return raster_grid

    def apply_bloom_convolution(self, raster_grid):
        """Apply bloom using Gaussian convolution.

        This models:
        - Tight laser spot (95% of energy, σ=0.05mm)
        - Weak bloom scatter (5% of energy, σ=0.8mm)

        Args:
            raster_grid: Binary grid with laser hits

        Returns:
            Energy grid with bloom applied
        """
        print(f"\n  Applying bloom convolution...")
        start_time = time.time()

        # Convert sigmas from mm to grid cells
        spot_sigma_cells = self.laser_spot_sigma / self.resolution
        scatter_sigma_cells = self.bloom_scatter_sigma / self.resolution

        print(f"    Primary spot: σ={self.laser_spot_sigma}mm ({spot_sigma_cells:.1f} cells)")
        print(f"    Bloom scatter: σ={self.bloom_scatter_sigma}mm ({scatter_sigma_cells:.1f} cells)")

        # Apply tight laser spot Gaussian
        print(f"    Convolving primary spot...")
        primary_energy = gaussian_filter(raster_grid, sigma=spot_sigma_cells, mode='constant')

        # Apply bloom scatter Gaussian
        print(f"    Convolving bloom scatter...")
        scatter_energy = gaussian_filter(raster_grid, sigma=scatter_sigma_cells, mode='constant')

        # Combine: most energy in tight spot, little in scatter
        primary_fraction = 1.0 - self.scatter_fraction
        bloom_grid = primary_fraction * primary_energy + self.scatter_fraction * scatter_energy

        elapsed = time.time() - start_time
        print(f"  Convolution completed in {elapsed:.2f}s")
        print(f"  Max energy: {bloom_grid.max():.2f}")
        print(f"  Mean energy: {bloom_grid.mean():.2f}")

        return bloom_grid

    def simulate(self, paths, sample_distance=0.05, min_samples=10):
        """Run complete simulation: rasterize + convolve.

        Args:
            paths: List of LineString paths
            sample_distance: Sample spacing
            min_samples: Min samples per path

        Returns:
            Energy grid with bloom
        """
        # Rasterize paths
        raster_grid = self.rasterize_paths(paths, sample_distance, min_samples)

        # Apply bloom via convolution
        self.grid = self.apply_bloom_convolution(raster_grid)

        return self.grid

    def get_path_ambient_bloom(self, path, sample_radius_mm=1.5, num_samples=20):
        """Get average AMBIENT bloom AROUND a path (not on it).

        This measures bloom energy in the vicinity, indicating how much
        ambient exposure the path gets from nearby copper.

        Args:
            path: LineString path
            sample_radius_mm: Radius around path to sample ambient bloom (mm)
            num_samples: Number of points along path to check

        Returns:
            Average ambient bloom energy around the path
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

    def identify_underexposed_paths(self, paths, threshold_percentile=30):
        """Identify under-exposed paths."""
        print(f"\n  Analyzing path exposure levels...")

        path_energies = []
        for i, path in enumerate(paths):
            if (i + 1) % 100 == 0:
                print(f"    Analyzed {i + 1}/{len(paths)} paths...")
            energy = self.get_path_ambient_bloom(path, sample_radius_mm=1.5, num_samples=20)
            path_energies.append(energy)

        path_energies = np.array(path_energies)

        threshold = np.percentile(path_energies, threshold_percentile)

        print(f"\n  Energy statistics:")
        print(f"    Min: {path_energies.min():.2f}")
        print(f"    Max: {path_energies.max():.2f}")
        print(f"    Mean: {path_energies.mean():.2f}")
        print(f"    Median: {np.median(path_energies):.2f}")
        print(f"    {threshold_percentile}th percentile: {threshold:.2f}")

        normal_paths = []
        underexposed_paths = []

        for path, energy in zip(paths, path_energies):
            if energy < threshold:
                underexposed_paths.append(path)
            else:
                normal_paths.append(path)

        print(f"\n  Classification:")
        print(f"    Normal: {len(normal_paths)}")
        print(f"    Under-exposed: {len(underexposed_paths)}")
        print(f"    Under-exposed %: {len(underexposed_paths) / len(paths) * 100:.1f}%")

        return normal_paths, underexposed_paths, path_energies


def visualize_results(simulator, paths, normal_paths, underexposed_paths,
                      geometry, output_file="bloom_fast.png"):
    """Visualize blooming simulation results."""

    print(f"\n  Creating visualization...")

    fig = plt.figure(figsize=(24, 10))
    gs = fig.add_gridspec(1, 3, width_ratios=[1, 1, 1])
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])
    ax3 = fig.add_subplot(gs[2])

    # Plot 1: Energy heatmap
    ax1.set_title('Blooming Energy (Realistic Laser Physics)', fontsize=14, fontweight='bold')
    ax1.set_aspect('equal')
    ax1.set_xlabel('X (mm)')
    ax1.set_ylabel('Y (mm)')

    colors = ['#000033', '#0000FF', '#00FFFF', '#FFFF00', '#FF0000']
    cmap = LinearSegmentedColormap.from_list('bloom', colors, N=256)

    min_x, min_y, max_x, max_y = simulator.bounds

    im = ax1.imshow(simulator.grid, cmap=cmap, origin='lower',
                    extent=[min_x, max_x, min_y, max_y],
                    interpolation='nearest', aspect='equal')

    plt.colorbar(im, ax=ax1, label='Bloom Energy')

    # Overlay copper geometry
    if isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            x, y = poly.exterior.xy
            ax1.plot(x, y, 'white', linewidth=0.5, alpha=0.5)
    elif isinstance(geometry, Polygon):
        x, y = geometry.exterior.xy
        ax1.plot(x, y, 'white', linewidth=0.5, alpha=0.5)

    # Plot 2: All paths
    ax2.set_title('All Fill Paths', fontsize=14, fontweight='bold')
    ax2.set_aspect('equal')
    ax2.grid(True, alpha=0.3)
    ax2.set_xlabel('X (mm)')
    ax2.set_ylabel('Y (mm)')

    if isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            x, y = poly.exterior.xy
            ax2.fill(x, y, color='lightgray', alpha=0.3, edgecolor='black', linewidth=0.5)
    elif isinstance(geometry, Polygon):
        x, y = geometry.exterior.xy
        ax2.fill(x, y, color='lightgray', alpha=0.3, edgecolor='black', linewidth=0.5)

    for path in paths:
        coords = list(path.coords)
        xs, ys = zip(*coords)
        ax2.plot(xs, ys, color='gray', linewidth=0.5, alpha=0.5)

    # Plot 3: Under-exposed highlighted
    ax3.set_title('Under-Exposed Paths (2x Exposure)', fontsize=14, fontweight='bold')
    ax3.set_aspect('equal')
    ax3.grid(True, alpha=0.3)
    ax3.set_xlabel('X (mm)')
    ax3.set_ylabel('Y (mm)')

    if isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            x, y = poly.exterior.xy
            ax3.fill(x, y, color='lightgray', alpha=0.3, edgecolor='black', linewidth=0.5)
    elif isinstance(geometry, Polygon):
        x, y = geometry.exterior.xy
        ax3.fill(x, y, color='lightgray', alpha=0.3, edgecolor='black', linewidth=0.5)

    for i, path in enumerate(normal_paths):
        coords = list(path.coords)
        xs, ys = zip(*coords)
        label = 'Normal' if i == 0 else ''
        ax3.plot(xs, ys, color='blue', linewidth=0.8, alpha=0.6, label=label)

    for i, path in enumerate(underexposed_paths):
        coords = list(path.coords)
        xs, ys = zip(*coords)
        label = 'Under-exposed (2x)' if i == 0 else ''
        ax3.plot(xs, ys, color='red', linewidth=1.5, alpha=0.9, label=label)

    ax3.legend(loc='upper right', fontsize=10)

    normal_length = sum(p.length for p in normal_paths)
    under_length = sum(p.length for p in underexposed_paths)
    total_length = normal_length + under_length

    stats_text = f"Statistics:\n"
    stats_text += f"Normal: {len(normal_paths)} ({normal_length:.1f}mm)\n"
    stats_text += f"Under-exposed: {len(underexposed_paths)} ({under_length:.1f}mm)\n"
    stats_text += f"Under-exposed %: {under_length / total_length * 100:.1f}%\n"
    stats_text += f"\nLaser spot: σ={simulator.laser_spot_sigma}mm\n"
    stats_text += f"Bloom: σ={simulator.bloom_scatter_sigma}mm"

    ax3.text(0.02, 0.98, stats_text, transform=ax3.transAxes,
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
             fontsize=9, family='monospace')

    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"  Saved to: {output_file}")


if __name__ == "__main__":
    gerber_folder = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13")
    copper_file = gerber_folder / "Gerber_TopLayer.GTL"

    if not copper_file.exists():
        print(f"Error: File not found: {copper_file}")
        sys.exit(1)

    print("\n" + "="*80)
    print("FAST BLOOMING SIMULATION (Convolution + Realistic Laser Physics)")
    print("="*80)

    # Parse Gerber
    print("\n[1/5] Parsing Gerber...")
    parser = GerberParser(copper_file)
    geometry = parser.parse()
    trace_centerlines = parser.get_trace_centerlines()
    pads = parser.get_pads()
    drill_holes = parser.get_drill_holes()

    # Generate fills
    print("\n[2/5] Generating fill paths...")
    fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)
    paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines,
                                    pads=pads, drill_holes=drill_holes)
    print(f"  Generated {len(paths)} paths")

    # Create simulator
    print("\n[3/5] Creating simulator...")
    simulator = FastBloomSimulator(
        resolution=0.05,          # 0.05mm grid
        laser_spot_sigma=0.05,    # Tight 0.06mm spot
        bloom_scatter_sigma=3.0,  # Wide bloom/scatter (3mm - reaches across multiple pads!)
        scatter_fraction=0.5      # 50/50 spot vs scatter (HEAVY blooming!)
    )

    bounds = geometry.bounds
    simulator.create_grid(bounds)

    # Run simulation
    print("\n[4/5] Running simulation...")
    overall_start = time.time()
    simulator.simulate(paths, sample_distance=0.05, min_samples=10)
    overall_elapsed = time.time() - overall_start
    print(f"\n  TOTAL SIMULATION TIME: {overall_elapsed:.2f}s")

    # Identify under-exposed
    print("\n[5/5] Identifying under-exposed paths...")
    normal_paths, underexposed_paths, energies = simulator.identify_underexposed_paths(
        paths, threshold_percentile=30
    )

    # Visualize
    visualize_results(simulator, paths, normal_paths, underexposed_paths,
                     geometry, "bloom_fast.png")

    print("\n" + "="*80)
    print("COMPLETE!")
    print("="*80)
