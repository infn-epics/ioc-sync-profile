# IOC Sync Profile

A Python-based EPICS softIOC for monitoring synchronization profiles of PV update times. It calculates instant and statistical frequencies for each input PV based on their update timestamps, as well as time differences and their statistics between pairs of PVs based on update times.

## Features

- Monitors specified EPICS PVs and tracks their update timestamps.
- For each PV:
  - Instant frequency (based on time between updates).
  - Average, minimum, maximum, and standard deviation of frequency over a rolling window.
- For each pair of PVs:
  - Current time difference between their latest update times.
  - Average, minimum, maximum, and standard deviation of time differences between paired updates.

## Requirements

- Python 3.6+
- caproto
- pyepics
- numpy

Install dependencies with:

```bash
pip install caproto pyepics numpy
```

## Usage

Run the IOC with a list of PV names to monitor:

```bash
python sync_profile_ioc.py PV1 PV2 PV3
```

The IOC will start and create output PVs for the calculations.

## PV Structure

### Frequency PVs (per input PV)

- `{PV}:InstantFreq` - Instantaneous frequency (Hz)
- `{PV}:AvgFreq` - Average frequency (Hz)
- `{PV}:MinFreq` - Minimum frequency (Hz)
- `{PV}:MaxFreq` - Maximum frequency (Hz)
- `{PV}:StdFreq` - Standard deviation of frequency (Hz)

### Difference PVs (per pair of PVs)

- `{PV1}_vs_{PV2}:CurrentDiff` - Current time difference (seconds)
- `{PV1}_vs_{PV2}:AvgDiff` - Average time difference (seconds)
- `{PV1}_vs_{PV2}:MinDiff` - Minimum time difference (seconds)
- `{PV1}_vs_{PV2}:MaxDiff` - Maximum time difference (seconds)
- `{PV1}_vs_{PV2}:StdDiff` - Standard deviation of time difference (seconds)

## Example

Assuming you have timestamp PVs `TIMESTAMP:PV1`, `TIMESTAMP:PV2`, and `TIMESTAMP:PV3`:

```bash
python sync_profile_ioc.py TIMESTAMP:PV1 TIMESTAMP:PV2 TIMESTAMP:PV3
```

This will create PVs like:

- `TIMESTAMP:PV1:InstantFreq`
- `TIMESTAMP:PV1_vs_TIMESTAMP:PV2:CurrentDiff`
- etc.

Monitor these PVs using EPICS tools such as `caget` or Phoebus.

## Configuration

- The rolling window size for statistics is set to 100 samples by default. Modify `self.window_size` in the code if needed.
- Ensure the input PVs are accessible and updating regularly for accurate frequency calculations.

## License

This project is provided as-is for educational and research purposes.