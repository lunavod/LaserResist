# Bloom Compensation Integration Guide

This guide shows how to integrate the bloom compensation feature into the CLI.

## Files Created

1. **src/laserresist/bloom_compensator.py** - Core bloom simulation module (already created)
2. This integration guide

## Changes Needed in src/laserresist/cli.py

### 1. Add Import (around line 20)

```python
from .bloom_compensator import FastBloomSimulator, identify_underexposed_traces, generate_compensation_paths
```

### 2. Add Config Keys (around line 129, in the `known_keys` set)

Add these keys to the known_keys set:
```python
'bloom_compensation', 'bloom_resolution', 'bloom_spot_sigma',
'bloom_scatter_sigma', 'bloom_scatter_fraction', 'bloom_threshold_percentile',
```

### 3. Add CLI Arguments (around line 258, in the fill_group)

```python
fill_group.add_argument(
    "--bloom-compensation",
    action="store_true",
    help="Enable bloom compensation for isolated traces (default: False)",
)
fill_group.add_argument(
    "--bloom-resolution",
    type=float,
    help="Bloom simulation grid resolution in mm (default: 0.05)",
)
fill_group.add_argument(
    "--bloom-scatter-sigma",
    type=float,
    help="Bloom scatter Gaussian sigma in mm (default: 2.0)",
)
fill_group.add_argument(
    "--bloom-scatter-fraction",
    type=float,
    help="Fraction of energy in bloom scatter vs tight spot (default: 0.35)",
)
fill_group.add_argument(
    "--bloom-threshold-percentile",
    type=float,
    help="Percentile threshold for under-exposure detection (default: 30)",
)
```

### 4. Get Config Values (around line 470, after isolation_threshold)

```python
bloom_compensation = get_value('bloom_compensation', default=False)
bloom_resolution = get_value('bloom_resolution', default=0.05)
bloom_spot_sigma = get_value('bloom_spot_sigma', default=0.05)
bloom_scatter_sigma = get_value('bloom_scatter_sigma', default=2.0)
bloom_scatter_fraction = get_value('bloom_scatter_fraction', default=0.35)
bloom_threshold_percentile = get_value('bloom_threshold_percentile', default=30)
```

### 5. Print Settings (around line 512, after bed_mesh section)

```python
if bloom_compensation:
    print(f"  Bloom compensation: enabled (scatter={bloom_scatter_sigma}mm, threshold={bloom_threshold_percentile}%)")
```

### 6. Integrate Bloom Compensation (around line 634, AFTER the fill generation section)

Replace/modify the section after `isolated_paths = []` to add bloom compensation logic:

```python
    # Handle both list and dict return types
    if isinstance(result, dict):
        paths = result['normal']
        isolated_paths = result['isolated']
    else:
        paths = result
        isolated_paths = []

    # NEW: Bloom compensation
    bloom_compensation_paths = []
    if bloom_compensation:
        print(f"\nRunning bloom compensation analysis...")

        # Create simulator
        simulator = FastBloomSimulator(
            resolution=bloom_resolution,
            laser_spot_sigma=bloom_spot_sigma,
            bloom_scatter_sigma=bloom_scatter_sigma,
            scatter_fraction=bloom_scatter_fraction
        )

        # Create grid and simulate
        simulator.create_grid(geometry.bounds)
        simulator.simulate(paths, sample_distance=0.05, min_samples=10)

        # Identify under-exposed traces
        normal_traces, underexposed_traces = identify_underexposed_traces(
            simulator,
            trace_centerlines,
            threshold_percentile=bloom_threshold_percentile,
            min_trace_length=0.2,
            verbose=args.verbose
        )

        # Generate compensation paths
        if underexposed_traces:
            print(f"  Identified {len(underexposed_traces)} under-exposed traces")
            bloom_compensation_paths = generate_compensation_paths(
                underexposed_traces,
                fill_gen
            )
            print(f"  Generated {len(bloom_compensation_paths)} compensation paths")

    total_length = sum(path.length for path in paths)
    isolated_length = sum(path.length for path in isolated_paths)
    bloom_length = sum(path.length for path in bloom_compensation_paths)

    print(f"  Generated {len(paths)} normal paths", end='')
    if isolated_paths:
        print(f", {len(isolated_paths)} isolated paths", end='')
    if bloom_compensation_paths:
        print(f", {len(bloom_compensation_paths)} bloom compensation paths", end='')
    print()

    if isolated_paths or bloom_compensation_paths:
        print(f"  Total length: {total_length:.2f}mm normal", end='')
        if isolated_paths:
            print(f" + {isolated_length:.2f}mm isolated (2x)", end='')
        if bloom_compensation_paths:
            print(f" + {bloom_length:.2f}mm bloom comp (2x)", end='')
        print()
    else:
        print(f"  Total length: {total_length:.2f} mm")
```

### 7. Pass Bloom Paths to G-code Generator (around line 659)

Modify the G-code generation call to include bloom compensation paths:

```python
    # Combine isolated paths and bloom compensation paths
    double_expose_paths = isolated_paths if isolated_paths else []
    if bloom_compensation_paths:
        double_expose_paths.extend(bloom_compensation_paths)

    with open(output_file, 'w') as f:
        gcode_gen.generate(paths, f, bounds, board_outline_bounds,
                         isolated_paths=double_expose_paths if double_expose_paths else None)
```

## Config File Examples

### config_example.yaml

Add to the fill generation section:

```yaml
# Bloom compensation (experimental)
bloom_compensation: false         # Enable bloom compensation for isolated traces
bloom_resolution: 0.05            # Simulation grid resolution in mm
bloom_scatter_sigma: 2.0          # Bloom scatter Gaussian sigma in mm
bloom_scatter_fraction: 0.35      # Fraction of energy in scatter (0-1)
bloom_threshold_percentile: 30    # Percentile threshold for detection
```

### config_example.json

Add to the JSON:

```json
{
  "bloom_compensation": false,
  "bloom_resolution": 0.05,
  "bloom_scatter_sigma": 2.0,
  "bloom_scatter_fraction": 0.35,
  "bloom_threshold_percentile": 30
}
```

## Usage Examples

### CLI

```bash
# Enable bloom compensation with defaults
laserresist board.gtl --bloom-compensation -o output.gcode

# Custom bloom parameters
laserresist board.gtl --bloom-compensation \
  --bloom-scatter-sigma 3.0 \
  --bloom-threshold-percentile 20 \
  -o output.gcode
```

### Config File

```yaml
# config.yaml
bloom_compensation: true
bloom_scatter_sigma: 2.5
bloom_threshold_percentile: 25
laser_power: 6.0
feed_rate: 1400.0
```

```bash
laserresist board.gtl --config config.yaml -o output.gcode
```

## Testing

Test the integration with:

```bash
python -m laserresist examples/test.gtl --bloom-compensation --verbose -o test_bloom.gcode
```

The output should show:
1. Normal fill path generation
2. "Running bloom compensation analysis..."
3. Number of under-exposed traces identified
4. Number of bloom compensation paths generated
5. Combined statistics

## Notes

- Bloom compensation adds ~2-5 seconds to processing time
- Requires scipy for Gaussian filtering
- Works alongside existing `--double-expose-isolated` feature
- Both isolated paths and bloom compensation paths get double exposure
