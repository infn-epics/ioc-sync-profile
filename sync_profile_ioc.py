#!/usr/bin/env python3

import argparse
import time
import threading
import numpy as np
from caproto.server import pvproperty, PVGroup, ioc_arg_parser, run
from caproto import ChannelType
import epics

class SyncProfileIOC(PVGroup):
    def __init__(self, pv_names, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pv_names = pv_names
        self.num_pvs = len(pv_names)
        self.data = {name: {'times': [], 'freqs': []} for name in pv_names}
        self.last_update = {name: time.time() for name in pv_names}
        self.window_size = 100  # Number of samples for stats

        # Create PVs for each input PV stats
        for i, name in enumerate(pv_names):
            setattr(self, f'instant_freq_{i}', pvproperty(value=0.0, dtype=ChannelType.DOUBLE, name=f'{name}:InstantFreq'))
            setattr(self, f'avg_freq_{i}', pvproperty(value=0.0, dtype=ChannelType.DOUBLE, name=f'{name}:AvgFreq'))
            setattr(self, f'min_freq_{i}', pvproperty(value=0.0, dtype=ChannelType.DOUBLE, name=f'{name}:MinFreq'))
            setattr(self, f'max_freq_{i}', pvproperty(value=0.0, dtype=ChannelType.DOUBLE, name=f'{name}:MaxFreq'))
            setattr(self, f'std_freq_{i}', pvproperty(value=0.0, dtype=ChannelType.DOUBLE, name=f'{name}:StdFreq'))

        # Create PVs for time diffs between PVs
        for i in range(self.num_pvs):
            for j in range(i+1, self.num_pvs):
                pair_name = f'{pv_names[i]}_vs_{pv_names[j]}'
                setattr(self, f'current_diff_{i}_{j}', pvproperty(value=0.0, dtype=ChannelType.DOUBLE, name=f'{pair_name}:CurrentDiff'))
                setattr(self, f'avg_diff_{i}_{j}', pvproperty(value=0.0, dtype=ChannelType.DOUBLE, name=f'{pair_name}:AvgDiff'))
                setattr(self, f'min_diff_{i}_{j}', pvproperty(value=0.0, dtype=ChannelType.DOUBLE, name=f'{pair_name}:MinDiff'))
                setattr(self, f'max_diff_{i}_{j}', pvproperty(value=0.0, dtype=ChannelType.DOUBLE, name=f'{pair_name}:MaxDiff'))
                setattr(self, f'std_diff_{i}_{j}', pvproperty(value=0.0, dtype=ChannelType.DOUBLE, name=f'{pair_name}:StdDiff'))

        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self.monitor_pvs)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

    def monitor_pvs(self):
        def callback(pvname, value, **kwargs):
            pv_timestamp = kwargs.get('timestamp', 0)
            name = pvname
            if name in self.data:
                self.data[name]['times'].append(pv_timestamp)
                if len(self.data[name]['times']) > 1:
                    dt = pv_timestamp - self.data[name]['times'][-2]
                    freq = 1.0 / dt if dt > 0 else 0.0
                    self.data[name]['freqs'].append(freq)
                    # Keep only recent samples
                    if len(self.data[name]['freqs']) > self.window_size:
                        self.data[name]['freqs'] = self.data[name]['freqs'][-self.window_size:]
                        self.data[name]['times'] = self.data[name]['times'][-self.window_size:]
                self.update_calculations()

        # Connect to PVs
        for name in self.pv_names:
            epics.camonitor(name, callback=callback)

        # Keep running
        while True:
            time.sleep(1)

    def update_calculations(self):
        # Update frequency stats for each PV
        for i, name in enumerate(self.pv_names):
            freqs = self.data[name]['freqs']
            if freqs:
                instant_freq = freqs[-1] if freqs else 0.0
                avg_freq = np.mean(freqs)
                min_freq = np.min(freqs)
                max_freq = np.max(freqs)
                std_freq = np.std(freqs)

                getattr(self, f'instant_freq_{i}').value = instant_freq
                getattr(self, f'avg_freq_{i}').value = avg_freq
                getattr(self, f'min_freq_{i}').value = min_freq
                getattr(self, f'max_freq_{i}').value = max_freq
                getattr(self, f'std_freq_{i}').value = std_freq

        # Update diff stats for each pair
        for i in range(self.num_pvs):
            for j in range(i+1, self.num_pvs):
                name1 = self.pv_names[i]
                name2 = self.pv_names[j]
                times1 = self.data[name1]['times']
                times2 = self.data[name2]['times']
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

                        getattr(self, f'current_diff_{i}_{j}').value = current_diff
                        getattr(self, f'avg_diff_{i}_{j}').value = avg_diff
                        getattr(self, f'min_diff_{i}_{j}').value = min_diff
                        getattr(self, f'max_diff_{i}_{j}').value = max_diff
                        getattr(self, f'std_diff_{i}_{j}').value = std_diff

def main():
    parser = argparse.ArgumentParser(description='EPICS Soft IOC for synchronization profile')
    parser.add_argument('pv_names', nargs='+', help='List of PV names to monitor')
    args = parser.parse_args()

    ioc = SyncProfileIOC(args.pv_names)
    run(ioc, **ioc_arg_parser.parse_known_args()[0])

if __name__ == '__main__':
    main()