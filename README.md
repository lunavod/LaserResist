# LaserResist

Generate laser exposure G-code from Gerber files for negative photoresist PCB fabrication.

Converts PCB Gerber files into G-code for laser-based photoresist exposure. Works with laser-equipped 3D printers and CNC machines running Klipper or other G-code firmware.

## Table of Contents

- [Why](#why)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage Examples](#usage-examples)
- [Parameter Reference](#parameter-reference)
- [Configuration Files](#configuration-files)
- [How It Works](#how-it-works)
- [Tips](#tips)
- [Requirements](#requirements)
- [License](#license)

## Why

Most PCB laser tools are designed for milling, not photoresist exposure. They either trace outlines without filling, or use fill patterns that avoid overlaps - which leaves gaps in tight geometries (like LightBurn's offset fill). They also don't account for laser dot size.

LaserResist uses a contour-based fill algorithm that completely covers all copper areas with intentional overlaps to prevent gaps. The outermost contour can be offset inward to compensate for laser spot size. Thin traces get centerline paths, and complex geometries like annular pads are handled automatically.

---

## Installation

```bash
git clone <repository-url>
cd LaserResist
pip install -e .
```

Requires Python 3.8+. Dependencies (installed automatically):
- gerbonara >= 1.0.0
- shapely >= 2.0.0
- numpy >= 1.20.0
- matplotlib >= 3.5.0

For YAML config file support: `pip install pyyaml`

---

## Quick Start

Single file:
```bash
laserresist input.gtl -o output.gcode
```

Folder auto-detection (finds copper layer, outline, drill files):
```bash
laserresist gerber_folder/ -o output.gcode
```

With config file:
```bash
laserresist input.gtl --config settings.yaml -o output.gcode
```

---

## Usage Examples

Custom laser settings:
```bash
laserresist board.gtl --laser-power 8.0 --feed-rate 1200 --line-spacing 0.08 -o output.gcode
```

Complete board with all files:
```bash
laserresist examples/ --outline board.gko --drill-pth holes.drl --drill-via vias.drl -o output.gcode
```

Klipper with bed mesh:
```bash
laserresist board.gtl --bed-mesh --mesh-offset 3.0 --probe-count "5,5" \
  --laser-arm-command "ARM_LASER" --laser-disarm-command "DISARM_LASER" -o output.gcode
```

Draw outline for positioning (use low power):
```bash
laserresist board.gtl --draw-outline --laser-power 2.0 -o output.gcode
```

High precision:
```bash
laserresist board.gtl --line-spacing 0.05 --initial-offset 0.03 --offset-centerlines -o output.gcode
```

---

## Parameter Reference

### Input/Output

| Parameter | Type | Description |
|-----------|------|-------------|
| `input` | Path | Input Gerber file or folder (required) |
| `-o, --output` | Path | Output G-code file (default: `exposure.gcode`) |
| `--config` | Path | Config file (JSON or YAML) |
| `-v, --verbose` | Flag | Show verbose output including parser warnings |

### Gerber File Options

| Parameter | Type | Description |
|-----------|------|-------------|
| `--outline` | Path | Board outline Gerber file (`.gko`, `.gm1`, etc.) |
| `--drill-pth` | Path | PTH (Plated Through Hole) drill file (`.drl`) |
| `--drill-via` | Path | Via drill file (`.drl`) |

### Fill Generation

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--line-spacing` | Float | `0.1` | Spacing between fill lines in mm |
| `--initial-offset` | Float | `0.05` | Inward offset of outer boundaries in mm (compensates for laser dot size) |
| `--offset-centerlines` | Flag | `false` | Offset trace centerlines from ends by line_spacing distance |

### Laser Settings

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--laser-power` | Float | `2.0` | Laser power percentage (0-100) |
| `--feed-rate` | Float | `1400.0` | Feed rate during exposure (mm/min) |
| `--travel-rate` | Float | `6000.0` | Rapid travel rate between paths (mm/min) |
| `--z-height` | Float | `20.0` | Z height for laser focus (mm) |

### Coordinates

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--x-offset` | Float | `0.0` | X offset (mm) |
| `--y-offset` | Float | `0.0` | Y offset (mm) |
| `--no-normalize` | Flag | `false` | Don't move pattern to origin |

### Bed Mesh (Klipper)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--bed-mesh` | Flag | `false` | Enable bed mesh calibration |
| `--mesh-offset` | Float | `3.0` | Mesh area offset from board edges (mm) |
| `--probe-count` | String | `"3,3"` | Probe grid size (e.g., `"5,5"`) |

### Laser Control

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--laser-arm-command` | String | None | Custom command to enable laser |
| `--laser-disarm-command` | String | None | Custom command to disable laser |
| `--draw-outline` | Flag | `false` | Draw board outline for positioning (use low power) |
| `--outline-offset-count` | Int | `0` | Outline offset copies: 0=single, 1=inward, -1=outward |

---

## Configuration Files

Save settings in JSON or YAML files:

### YAML Example

```yaml
# LaserResist Configuration File
# All settings are optional - defaults will be used if not specified

# Fill generation
line_spacing: 0.1          # Spacing between fill lines in mm
initial_offset: 0.05       # Initial inward offset of outer boundaries to compensate for laser dot size in mm
offset_centerlines: false  # Offset trace centerlines from ends

# Laser settings
laser_power: 6.0           # Laser power percentage (0-100)
feed_rate: 1400.0          # Feed rate for exposure in mm/min
travel_rate: 6000.0        # Rapid travel rate in mm/min
z_height: 20.0             # Z height for laser focus in mm

# Coordinate transformation
x_offset: 0.0              # X offset in mm
y_offset: 0.0              # Y offset in mm

# Bed mesh calibration (optional)
bed_mesh: true             # Enable bed mesh calibration
mesh_offset: 3.0           # Offset from board edges in mm
probe_count: "3,3"         # Probe points (X,Y)

# Laser control commands (optional)
laser_arm_command: "ARM_LASER"       # Command to enable laser relay
laser_disarm_command: "DISARM_LASER" # Command to disable laser relay

# Board outline drawing (optional)
draw_outline: false                  # Draw board outline before exposure (for positioning)
outline_offset_count: 0              # Offset copies: 0=single, -1=one outward, +1=one inward
```

### Example JSON Configuration

```json
{
  "line_spacing": 0.1,
  "initial_offset": 0.05,
  "offset_centerlines": false,
  "laser_power": 6.0,
  "feed_rate": 1400.0,
  "travel_rate": 6000.0,
  "z_height": 20.0,
  "x_offset": 0.0,
  "y_offset": 0.0,
  "bed_mesh": true,
  "mesh_offset": 3.0,
  "probe_count": "3,3",
  "laser_arm_command": "ARM_LASER",
  "laser_disarm_command": "DISARM_LASER",
  "draw_outline": false,
  "outline_offset_count": 0
}
```

### Priority

CLI arguments override config file values, which override defaults.

```bash
laserresist board.gtl --config settings.yaml --laser-power 8.0
# Uses 8.0 even if config file specifies different value
```

---

## How It Works

**Processing pipeline:**
```
Gerber Files → Parse → Generate Fill → G-code → Output
```

**Gerber parsing:**
Converts Gerber primitives to Shapely polygons, subtracts drill holes, extracts trace centerlines.

**Fill generation (contour offset method):**

1. Extract outermost boundaries (optionally offset inward by `initial_offset`)
2. Repeatedly buffer geometry inward by `line_spacing`, extracting boundaries at each step
3. When areas become too thin, add centerlines for complete coverage
4. Add trace centerlines, clipped to avoid pad areas
5. Special handling for thin annular pads (circular centerlines)

**G-code generation:**
Transforms coordinates, adds initialization (homing, bed mesh), converts paths to G1 moves with laser control (M106/M107), includes safety features.

### Generated G-code Structure

```gcode
; LaserResist Generated G-code
; Original bounds: X=[min, max] Y=[min, max]
; Settings: power=X%, feed=Ymm/min, spacing=Zmm

G28 ; Home
G90 ; Absolute positioning
G21 ; Millimeters

; Optional: Bed mesh calibration
BED_MESH_CALIBRATE MESH_MIN=X,Y MESH_MAX=X,Y PROBE_COUNT=X,Y

; Optional: Draw outline for positioning

; Exposure paths
G0 X... Y... F6000 ; Travel to start
M106 S... ; Laser on
G1 X... Y... F1400 ; Expose path
M107 ; Laser off
; ... (repeated for all paths)

M107 ; Ensure laser off
G28 ; Return home
M84 ; Motors off
```

---

## Tips

**Getting started:**
- Test positioning with `--draw-outline` at low power first
- Start with conservative laser power (3-5%) and increase if under-exposed
- Set `--initial-offset` to your laser spot radius
- Verify Z-height for proper focus

**Fill quality:**
- Smaller `line_spacing` = better coverage, longer exposure (start with 0.1mm)
- For gaps or incomplete fills, decrease `line_spacing`
- For traces wider than designed, increase `initial_offset`
- For traces narrower than designed, decrease `initial_offset`

**Speed vs quality:**
```
Fast:    line_spacing 0.15mm, feed_rate 2000mm/min
Quality: line_spacing 0.05mm, feed_rate 1000mm/min
```

**Laser power (405nm UV):**
Typically 2-10% for negative photoresist. Make test strips to dial in settings.

**Bed mesh for large boards:**
```bash
laserresist board.gtl --bed-mesh --mesh-offset 5.0 --probe-count "7,7"
```

---

## Requirements

**Software:**
- Python 3.8+
- PCB design software that exports Gerber files (KiCad, EasyEDA, Altium, EAGLE, etc.)

**Hardware:**
- Laser-equipped machine (3D printer with laser module, laser CNC, etc.)
- Firmware: Klipper, Marlin, GRBL, or any G-code firmware
- UV laser (405nm recommended) or CO2 laser
- Negative dry film photoresist

**Gerber files:**
- Copper layer (top or bottom) - required
- Board outline - optional but recommended
- Drill files (PTH/Via) - optional
- Formats: Gerber RS-274X (`.gbr`, `.gtl`, `.gbl`), Excellon (`.drl`, `.txt`)

---

## License

MIT License

Copyright (c) 2024 Yegor

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

---

## Contributing

Issues and pull requests welcome.
