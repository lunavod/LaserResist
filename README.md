# LaserResist

Converts PCB Gerber files to G-code for laser photoresist exposure. Built for laser-equipped 3D printers and CNC machines.

## Why This Exists

Most PCB laser tools are designed for milling, not photoresist exposure. They either trace outlines without filling or use fill patterns that avoid overlaps, which leaves gaps in tight geometries. They also don't account for laser dot size.

LaserResist uses a contour-based fill algorithm that completely covers all copper areas with intentional overlaps. The outermost contour is offset inward to compensate for laser spot size. Thin traces get centerline paths, and complex geometries like annular pads are handled automatically.

Includes bloom compensation to identify and double-expose isolated traces that would otherwise be under-exposed due to lack of ambient light scatter.

## Installation

```bash
git clone <repository-url>
cd LaserResist
pip install -e .
```

Requires Python 3.8+. Main dependencies (auto-installed):
- gerbonara >= 1.0.0
- shapely >= 2.0.0
- numpy >= 1.20.0
- matplotlib >= 3.5.0
- scipy (for bloom compensation)

For YAML config support: `pip install pyyaml`

## Quick Start

Single file:
```bash
laserresist input.gtl -o output.gcode
```

Folder auto-detection (finds copper, outline, drill files):
```bash
laserresist gerber_folder/ -o output.gcode
```

With config file:
```bash
laserresist input.gtl --config settings.yaml -o output.gcode
```

## Usage Examples

Basic with custom settings:
```bash
laserresist board.gtl --laser-power 8.0 --feed-rate 1200 --line-spacing 0.08 -o output.gcode
```

Complete board with drill files:
```bash
laserresist examples/ --outline board.gko --drill-pth holes.drl -o output.gcode
```

Back side (folder auto-detection with flip):
```bash
laserresist gerber_folder/ --side back --flip-horizontal -o back.gcode
```

Klipper with bed mesh:
```bash
laserresist board.gtl --bed-mesh --mesh-offset 3.0 --probe-count "5,5" \
  --laser-arm-command "ARM_LASER" --laser-disarm-command "DISARM_LASER" -o output.gcode
```

With bloom compensation (recommended for better results):
```bash
laserresist board.gtl --bloom-compensation --bloom-debug-image -o output.gcode
```

Draw outline for positioning (low power):
```bash
laserresist board.gtl --draw-outline --laser-power 2.0 -o output.gcode
```

High precision with forced pad centerlines:
```bash
laserresist board.gtl --line-spacing 0.05 --initial-offset 0.03 \
  --forced-pad-centerlines -o output.gcode
```

## Parameter Reference

### Input/Output

| Parameter | Type | Description |
|-----------|------|-------------|
| `input` | Path | Gerber file or folder (required) |
| `-o, --output` | Path | Output G-code file (default: exposure.gcode) |
| `--config` | Path | JSON or YAML config file |
| `-v, --verbose` | Flag | Show verbose output and parser warnings |

### Gerber Files

| Parameter | Type | Description |
|-----------|------|-------------|
| `--side` | String | For folder auto-detection: front/top (default) or back/bottom |
| `--outline` | Path | Board outline Gerber (.gko, .gm1) |
| `--drill-pth` | Path | PTH drill file (.drl) |
| `--drill-via` | Path | Via drill file (.drl) |

### Fill Generation

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--line-spacing` | Float | 0.1 | Spacing between fill lines (mm) |
| `--initial-offset` | Float | 0.05 | Inward offset for laser spot compensation (mm) |
| `--forced-pad-centerlines` | Flag | false | Add + centerlines to rectangular pads, circles to round pads |
| `--offset-centerlines` | Flag | false | Offset trace centerlines from ends by line_spacing |
| `--force-trace-centerlines` | Flag | false | Force centerlines for all traces |
| `--force-trace-centerlines-max-thickness` | Float | 0.5 | Max trace width for forced centerlines (mm) |

### Bloom Compensation

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--bloom-compensation` | Flag | false | Enable bloom compensation for isolated traces |
| `--bloom-resolution` | Float | 0.05 | Grid resolution for bloom simulation (mm) |
| `--bloom-spot-sigma` | Float | 0.05 | Laser spot size sigma (mm) |
| `--bloom-scatter-sigma` | Float | 2.0 | Bloom scatter radius sigma (mm) |
| `--bloom-scatter-fraction` | Float | 0.35 | Fraction of energy that scatters (0-1) |
| `--bloom-threshold-percentile` | Int | 30 | Percentile threshold for under-exposure (0-100) |
| `--bloom-debug-image` | Flag | false | Generate debug visualization PNG |

### Double Exposure

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--double-expose-isolated` | Flag | false | Double expose isolated features |
| `--isolation-threshold` | Float | 1.0 | Distance threshold for isolation detection (mm) |

### Laser Settings

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--laser-power` | Float | 2.0 | Laser power (0-100%) |
| `--feed-rate` | Float | 1400.0 | Exposure feed rate (mm/min) |
| `--travel-rate` | Float | 6000.0 | Rapid travel rate (mm/min) |
| `--z-height` | Float | 20.0 | Z height for focus (mm) |

### Coordinates

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--x-offset` | Float | 0.0 | X offset (mm) |
| `--y-offset` | Float | 0.0 | Y offset (mm) |
| `--no-normalize` | Flag | false | Don't move pattern to origin |
| `--flip-horizontal` | Flag | false | Mirror X axis (for bottom layer) |

### Klipper Features

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--bed-mesh` | Flag | false | Enable bed mesh calibration |
| `--mesh-offset` | Float | 3.0 | Mesh offset from board edges (mm) |
| `--probe-count` | String | "3,3" | Probe grid size (e.g., "5,5") |
| `--laser-arm-command` | String | None | Command to enable laser (e.g., ARM_LASER) |
| `--laser-disarm-command` | String | None | Command to disable laser |

### Board Outline

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--draw-outline` | Flag | false | Draw board outline for positioning |
| `--outline-offset-count` | Int | 0 | Offset copies: 0=single, -1=outward, 1=inward |

## Configuration Files

Settings can be saved in JSON or YAML files. CLI arguments override config file values.

### YAML Example

```yaml
# LaserResist Config

# Gerber selection
side: "front"

# Fill settings
line_spacing: 0.1
initial_offset: 0.05
forced_pad_centerlines: true

# Bloom compensation
bloom_compensation: true
bloom_scatter_sigma: 2.0
bloom_scatter_fraction: 0.35
bloom_threshold_percentile: 30

# Laser
laser_power: 6.0
feed_rate: 1400.0
travel_rate: 6000.0
z_height: 20.0

# Coordinates
x_offset: 0.0
y_offset: 0.0
flip_horizontal: false

# Klipper
bed_mesh: true
mesh_offset: 3.0
probe_count: "3,3"
laser_arm_command: "ARM_LASER"
laser_disarm_command: "DISARM_LASER"

# Outline
draw_outline: false
outline_offset_count: 0
```

Usage:
```bash
laserresist board.gtl --config settings.yaml --laser-power 8.0
# CLI args override config file
```

## How It Works

Pipeline:
```
Gerber Files -> Parse -> Generate Fill -> G-code -> Output
```

### Gerber Parsing

Converts Gerber primitives to Shapely polygons, subtracts drill holes, extracts trace centerlines with width information.

### Fill Generation

Uses contour offset method:

1. Extract outermost boundaries (offset inward by initial_offset)
2. Repeatedly buffer geometry inward by line_spacing, extracting boundaries at each step
3. When areas become too thin, add centerlines for complete coverage
4. Add trace centerlines, clipped to avoid pad areas
5. Handle thin annular pads with circular centerlines
6. Optional: Add forced centerlines to all pads (+ for rectangular, circles for round)
7. Optional: Identify isolated features and mark for double exposure
8. Optional: Run bloom simulation to find under-exposed traces and generate compensation paths

### Bloom Compensation

Simulates laser scatter using Gaussian convolution on a rasterized grid. Identifies traces with low ambient bloom (isolated traces) and generates additional fill paths that are exposed twice. This compensates for the physics of photoresist exposure where isolated features receive less scattered light than features surrounded by copper.

The simulation accounts for:
- Tight laser spot (primary energy)
- Bloom scatter (secondary energy, typically 35% of total)
- Ambient exposure from nearby copper areas

Drill holes are properly subtracted from compensation paths to avoid exposing over holes.

### G-code Generation

Transforms coordinates, adds initialization (homing, bed mesh calibration), converts paths to G1 moves with laser control (M3/M5 or M106/M107), includes safety features.

G-code structure:
```gcode
; LaserResist Generated
; Settings in header comments

G28                 ; Home
G90                 ; Absolute positioning
G21                 ; Millimeters
M5                  ; Laser off

; Bed mesh (if enabled)
BED_MESH_CALIBRATE MESH_MIN=X,Y MESH_MAX=X,Y PROBE_COUNT=X,Y

ARM_LASER           ; Enable relay (if configured)

; Board outline (if enabled)
; ...

; Exposure paths
G0 X... Y... F6000  ; Travel
M3 S...             ; Laser on
G1 X... Y... F1400  ; Expose
M5                  ; Laser off
; ...

M5                  ; Ensure laser off
DISARM_LASER        ; Disable relay (if configured)
G28                 ; Home
M84                 ; Motors off
```

## Tips

### Getting Started

Test positioning with `--draw-outline` at low power first. Start with conservative laser power (3-5%) and increase if under-exposed. Set `initial_offset` to your laser spot radius. Verify Z-height for proper focus.

### Fill Quality

Smaller line_spacing = better coverage but longer exposure (start with 0.1mm). For gaps or incomplete fills, decrease line_spacing. For traces wider than designed, increase initial_offset. For traces narrower than designed, decrease initial_offset.

Use `--forced-pad-centerlines` for better pad center exposure, especially for fine pitch components. Use `--bloom-compensation` to fix under-exposure of isolated traces.

### Speed vs Quality

Fast: line_spacing 0.15mm, feed_rate 2000mm/min
Quality: line_spacing 0.05mm, feed_rate 1000mm/min

### Laser Power

For 405nm UV on negative photoresist, typically 2-10%. Make test strips to dial in your settings.

### Bloom Compensation

Bloom compensation is recommended for boards with isolated traces or fine features. It adds 20-40% extra paths that are exposed twice. The default parameters work well for most setups but can be tuned:

- Increase `bloom_scatter_sigma` if you have a powerful laser with more scatter
- Increase `bloom_scatter_fraction` if your resist is very sensitive to ambient light
- Decrease `bloom_threshold_percentile` to be more aggressive (compensate more traces)

Use `--bloom-debug-image` to generate a visualization showing which traces are being compensated.

## Requirements

**Software:**
- Python 3.8+
- PCB design software that exports Gerber (KiCad, EasyEDA, Altium, EAGLE, etc.)

**Hardware:**
- Laser-equipped machine (3D printer with laser module, laser CNC)
- Firmware: Klipper (recommended), Marlin, GRBL, or any G-code firmware
- UV laser (405nm recommended) or CO2 laser
- Negative dry film photoresist

**Gerber Files:**
- Copper layer (required) - .gbr, .gtl, .gbl
- Board outline (recommended) - .gko, .gm1
- Drill files (optional) - .drl, .txt
- Format: Gerber RS-274X, Excellon

## License

MIT License

Copyright (c) 2024 Yegor

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Contributing

Issues and pull requests welcome.
