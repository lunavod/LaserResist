# LaserResist

Generate laser exposure G-code from Gerber files for negative photoresist PCB fabrication.

## Overview

LaserResist converts PCB Gerber files into optimized G-code for laser-based photoresist exposure. Designed for makers using laser-equipped 3D printers (like Klipper-based systems) to expose negative dry film photoresist.

## The Problem

Most PCB laser exposure tools either:
- Focus on milling instead of photoresist exposure
- Only trace outlines instead of completely filling areas
- Avoid overlaps, leaving gaps in tight geometries (like LightBurn's offset fill)

LaserResist solves this by generating fill patterns that:
- Completely cover all traces, pads, and copper areas
- Allow/encourage overlaps to ensure no gaps
- Optimize for photoresist exposure, not milling

## Features (Planned)

- Parse Gerber files to extract copper geometry
- Generate complete fill patterns for all copper areas
- Configurable line spacing, laser power, and feed rates
- G-code output compatible with Klipper and other firmware
- No gaps in tight geometries

## Installation

```bash
pip install -e .
```

## Usage

```bash
laserresist input.gbr -o output.gcode
```

## Requirements

- Python >= 3.8
- Gerber files from your PCB design software (KiCad, EasyEDA, etc.)
- Laser-equipped machine running Klipper or compatible firmware

## License

MIT
