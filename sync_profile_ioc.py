#!/usr/bin/env python3

import argparse
import time
import threading
import numpy as np
from softioc import softioc, builder
import epics
import yaml

def main():
    parser = argparse.ArgumentParser(description='EPICS Soft IOC for synchronization profile')
    parser.add_argument('--config', required=True, help='YAML config file with devices to monitor')
    parser.add_argument("-p", "--pvout", required=False, default="pvlist.txt", help="Output PV list file")
    parser.add_argument("--prefix", default="SYNC", help="IOC prefix for PV names")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)
    devices = config['devices']
    names = [d['name'] for d in devices]
    pvs = [d['pv'] for d in devices]
    name_to_pv = {d['name']: d['pv'] for d in devices}
    pv_to_name = {d['pv']: d['name'] for d in devices}

    print(f"Loaded {len(devices)} devices from {args.config}")
    print("Monitoring PVs:")
    for name, pv in zip(names, pvs):
        print(f"  {name}: {pv}")
    print(f"IOC prefix: {args.prefix}")
    print(f"Output PV list file: {args.pvout}")

    num_pvs = len(pvs)
    data = {pv: {'times': [], 'freqs': []} for pv in pvs}
    window_size = 100  # Number of samples for stats

    # Set device name
    builder.SetDeviceName(args.prefix)

    # Create PVs for each input PV stats
    freq_pvs = {}
    for name in names:
        freq_pvs[name] = {
            'instant': builder.aIn(f'{name}:InstantFreq', initial_value=0.0),
            'avg': builder.aIn(f'{name}:AvgFreq', initial_value=0.0),
            'min': builder.aIn(f'{name}:MinFreq', initial_value=0.0),
            'max': builder.aIn(f'{name}:MaxFreq', initial_value=0.0),
            'std': builder.aIn(f'{name}:StdFreq', initial_value=0.0),
        }

    # Create PVs for time diffs between PVs
    diff_pvs = {}
    for i in range(num_pvs):
        for j in range(i+1, num_pvs):
            name1 = names[i]
            name2 = names[j]
            pair_name = f'{name1}_vs_{name2}'
            diff_pvs[(i, j)] = {
                'current': builder.aIn(f'{pair_name}:CurrentDiff', initial_value=0.0),
                'avg': builder.aIn(f'{pair_name}:AvgDiff', initial_value=0.0),
                'min': builder.aIn(f'{pair_name}:MinDiff', initial_value=0.0),
                'max': builder.aIn(f'{pair_name}:MaxDiff', initial_value=0.0),
                'std': builder.aIn(f'{pair_name}:StdDiff', initial_value=0.0),
            }

    print("Created output PVs:")
    for name in names:
        print(f"  Frequency stats for {name}: {args.prefix}:{name}:InstantFreq, AvgFreq, MinFreq, MaxFreq, StdFreq")
    for i in range(num_pvs):
        for j in range(i+1, num_pvs):
            name1 = names[i]
            name2 = names[j]
            pair_name = f'{name1}_vs_{name2}'
            print(f"  Time diff stats for {name1} vs {name2}: {args.prefix}:{pair_name}:CurrentDiff, AvgDiff, MinDiff, MaxDiff, StdDiff")

    def monitor_pvs():
        def callback(pvname, value, **kwargs):
            pv_timestamp = kwargs.get('timestamp', time.time())
            name = pvname
            if name in data:
                data[name]['times'].append(pv_timestamp)
                if len(data[name]['times']) > 1:
                    dt = pv_timestamp - data[name]['times'][-2]
                    freq = 1.0 / dt if dt > 0 else 0.0
                    data[name]['freqs'].append(freq)
                    # Keep only recent samples
                    if len(data[name]['freqs']) > window_size:
                        data[name]['freqs'] = data[name]['freqs'][-window_size:]
                        data[name]['times'] = data[name]['times'][-window_size:]
                update_calculations()

        # Connect to PVs
        for pv in pvs:
            epics.camonitor(pv, callback=callback)

        # Keep running
        while True:
            time.sleep(1)

    def update_calculations():
        # Update frequency stats for each PV
        for name in names:
            pv = name_to_pv[name]
            freqs = data[pv]['freqs']
            if freqs:
                instant_freq = freqs[-1]
                avg_freq = np.mean(freqs)
                min_freq = np.min(freqs)
                max_freq = np.max(freqs)
                std_freq = np.std(freqs)

                freq_pvs[name]['instant'].set(instant_freq)
                freq_pvs[name]['avg'].set(avg_freq)
                freq_pvs[name]['min'].set(min_freq)
                freq_pvs[name]['max'].set(max_freq)
                freq_pvs[name]['std'].set(std_freq)

        # Update diff stats for each pair
        for i in range(num_pvs):
            for j in range(i+1, num_pvs):
                name1 = names[i]
                name2 = names[j]
                pv1 = name_to_pv[name1]
                pv2 = name_to_pv[name2]
                times1 = data[pv1]['times']
                times2 = data[pv2]['times']
                if times1 and times2:
                    # Current diff based on latest update times
                    current_diff = times1[-1] - times2[-1]
                    # For stats, use paired diffs (zip stops at shorter list)
                    diffs = [t1 - t2 for t1, t2 in zip(times1, times2)]
                    if diffs:
                        avg_diff = np.mean(diffs)
                        min_diff = np.min(diffs)
                        max_diff = np.max(diffs)
                        std_diff = np.std(diffs)

                        diff_pvs[(i, j)]['current'].set(current_diff)
                        diff_pvs[(i, j)]['avg'].set(avg_diff)
                        diff_pvs[(i, j)]['min'].set(min_diff)
                        diff_pvs[(i, j)]['max'].set(max_diff)
                        diff_pvs[(i, j)]['std'].set(std_diff)

    # Boilerplate get the IOC started
    builder.LoadDatabase()
    softioc.iocInit()

    # Start processes required to be run after iocInit
    monitor_thread = threading.Thread(target=monitor_pvs)
    monitor_thread.daemon = True
    monitor_thread.start()

    # Write PV list to file
    import os
    with open(args.pvout, "w") as f:
        old_stdout = os.dup(1)
        os.dup2(f.fileno(), 1)
        softioc.dbl()
        os.dup2(old_stdout, 1)
        os.close(old_stdout)

    # Leave the IOC running with an interactive shell.
    softioc.interactive_ioc(globals())

if __name__ == '__main__':
    main()