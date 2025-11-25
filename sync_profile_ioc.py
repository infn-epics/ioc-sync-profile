#!/usr/bin/env python3

import argparse
import time
import threading
import numpy as np
from softioc import softioc, builder
import epics
import yaml
import xml.etree.ElementTree as ET
import xml.dom.minidom

def main():
    parser = argparse.ArgumentParser(description='EPICS Soft IOC for synchronization profile')
    parser.add_argument('--config', required=True, help='YAML config file with devices to monitor')
    parser.add_argument("-p", "--pvout", required=False, default="pvlist.txt", help="Output PV list file")
    parser.add_argument("--prefix", default="SYNC", help="IOC prefix for PV names")
    parser.add_argument("--bob", default="sync_profile.bob", help="Output Phoebus .bob file")
    parser.add_argument("--create-display-only", action="store_true", help="Create Phoebus display file and exit without running IOC")
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
    timestamp_pvs = {}
    for name in names:
        freq_pvs[name] = {
            'instant': builder.aIn(f'{name}:InstantFreq', initial_value=0.0),
            'avg': builder.aIn(f'{name}:AvgFreq', initial_value=0.0),
            'min': builder.aIn(f'{name}:MinFreq', initial_value=0.0),
            'max': builder.aIn(f'{name}:MaxFreq', initial_value=0.0),
            'std': builder.aIn(f'{name}:StdFreq', initial_value=0.0),
        }
        timestamp_pvs[name] = builder.aIn(f'{name}:Timestamp', initial_value=0.0)

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
        print(f"  Stats for {name}: {args.prefix}:{name}:Timestamp, InstantFreq, AvgFreq, MinFreq, MaxFreq, StdFreq")
    for i in range(num_pvs):
        for j in range(i+1, num_pvs):
            name1 = names[i]
            name2 = names[j]
            pair_name = f'{name1}_vs_{name2}'
            print(f"  Time diff stats for {name1} vs {name2}: {args.prefix}:{pair_name}:CurrentDiff, AvgDiff, MinDiff, MaxDiff, StdDiff")

    # Generate Phoebus .bob file
    pv_list = []
    for name in names:
        pv_list.append(f"{args.prefix}:{name}:Timestamp")
        pv_list.append(f"{args.prefix}:{name}:InstantFreq")
        pv_list.append(f"{args.prefix}:{name}:AvgFreq")
        pv_list.append(f"{args.prefix}:{name}:MinFreq")
        pv_list.append(f"{args.prefix}:{name}:MaxFreq")
        pv_list.append(f"{args.prefix}:{name}:StdFreq")
    for i in range(num_pvs):
        for j in range(i+1, num_pvs):
            name1 = names[i]
            name2 = names[j]
            pair_name = f'{name1}_vs_{name2}'
            pv_list.append(f"{args.prefix}:{pair_name}:CurrentDiff")
            pv_list.append(f"{args.prefix}:{pair_name}:AvgDiff")
            pv_list.append(f"{args.prefix}:{pair_name}:MinDiff")
            pv_list.append(f"{args.prefix}:{pair_name}:MaxDiff")
            pv_list.append(f"{args.prefix}:{pair_name}:StdDiff")

    root = ET.Element("display", version="2.0.0")
    ET.SubElement(root, "name").text = "Sync Profile"
    column_width = 120
    x_start = 10
    y_start = 50
    row_height = 35
    width = x_start + 7 * column_width  # for device table
    height = 1000  # approximate, will adjust
    ET.SubElement(root, "width").text = str(width)
    ET.SubElement(root, "height").text = str(height)
    actions = ET.SubElement(root, "actions")
    actions.text = ""

    # Device stats table
    columns_device = ['Device', 'Timestamp', 'InstantFreq', 'AvgFreq', 'MinFreq', 'MaxFreq', 'StdFreq']
    y = y_start
    for col_idx, col in enumerate(columns_device):
        x = x_start + col_idx * column_width
        # Column label
        label = ET.SubElement(root, "widget", type="label", version="2.0.0")
        ET.SubElement(label, "name").text = f"Label_Device_{col}"
        ET.SubElement(label, "text").text = col
        ET.SubElement(label, "x").text = str(x)
        ET.SubElement(label, "y").text = "20"
        ET.SubElement(label, "width").text = str(column_width - 10)
        ET.SubElement(label, "height").text = "30"
        ET.SubElement(label, "horizontal_alignment").text = "1"
        font = ET.SubElement(label, "font")
        ET.SubElement(font, "font", name="Liberation Sans", style="BOLD", size="12.0")
        # Rows
        for row_idx, name in enumerate(names):
            yy = y + row_idx * row_height
            if col == 'Device':
                # Label for device name
                dev_label = ET.SubElement(root, "widget", type="label", version="2.0.0")
                ET.SubElement(dev_label, "name").text = f"Label_Device_{name}"
                ET.SubElement(dev_label, "text").text = name
                ET.SubElement(dev_label, "x").text = str(x)
                ET.SubElement(dev_label, "y").text = str(yy)
                ET.SubElement(dev_label, "width").text = str(column_width - 10)
                ET.SubElement(dev_label, "height").text = "30"
                ET.SubElement(dev_label, "horizontal_alignment").text = "1"
            else:
                pv = f"{args.prefix}:{name}:{col}"
                widget = ET.SubElement(root, "widget", type="textupdate", version="2.0.0")
                ET.SubElement(widget, "name").text = f"TextUpdate_{name}_{col}"
                ET.SubElement(widget, "pv_name").text = pv
                ET.SubElement(widget, "x").text = str(x)
                ET.SubElement(widget, "y").text = str(yy)
                ET.SubElement(widget, "width").text = str(column_width - 10)
                ET.SubElement(widget, "height").text = "30"
                ET.SubElement(widget, "horizontal_alignment").text = "1"
                ET.SubElement(widget, "vertical_alignment").text = "1"
                ET.SubElement(widget, "wrap_words").text = "false"
                actions = ET.SubElement(widget, "actions")
                actions.text = ""
                ET.SubElement(widget, "border_width").text = "1"

    # Diff stats table
    y_diff = y + len(names) * row_height + 50
    columns_diff = ['Pair', 'CurrentDiff', 'AvgDiff', 'MinDiff', 'MaxDiff', 'StdDiff']
    for col_idx, col in enumerate(columns_diff):
        x = x_start + col_idx * column_width
        # Column label
        label = ET.SubElement(root, "widget", type="label", version="2.0.0")
        ET.SubElement(label, "name").text = f"Label_Diff_{col}"
        ET.SubElement(label, "text").text = col
        ET.SubElement(label, "x").text = str(x)
        ET.SubElement(label, "y").text = str(y_diff - 30)
        ET.SubElement(label, "width").text = str(column_width - 10)
        ET.SubElement(label, "height").text = "30"
        ET.SubElement(label, "horizontal_alignment").text = "1"
        font = ET.SubElement(label, "font")
        ET.SubElement(font, "font", name="Liberation Sans", style="BOLD", size="12.0")
        # Rows
        pairs = [f'{names[i]}_vs_{names[j]}' for i in range(num_pvs) for j in range(i+1, num_pvs)]
        for row_idx, pair in enumerate(pairs):
            yy = y_diff + row_idx * row_height
            if col == 'Pair':
                # Label for pair name
                pair_label = ET.SubElement(root, "widget", type="label", version="2.0.0")
                ET.SubElement(pair_label, "name").text = f"Label_Pair_{pair}"
                ET.SubElement(pair_label, "text").text = pair.replace('_vs_', ' vs ')
                ET.SubElement(pair_label, "x").text = str(x)
                ET.SubElement(pair_label, "y").text = str(yy)
                ET.SubElement(pair_label, "width").text = str(column_width - 10)
                ET.SubElement(pair_label, "height").text = "30"
                ET.SubElement(pair_label, "horizontal_alignment").text = "1"
            else:
                pv = f"{args.prefix}:{pair}:{col}"
                widget = ET.SubElement(root, "widget", type="textupdate", version="2.0.0")
                ET.SubElement(widget, "name").text = f"TextUpdate_{pair}_{col}"
                ET.SubElement(widget, "pv_name").text = pv
                ET.SubElement(widget, "x").text = str(x)
                ET.SubElement(widget, "y").text = str(yy)
                ET.SubElement(widget, "width").text = str(column_width - 10)
                ET.SubElement(widget, "height").text = "30"
                ET.SubElement(widget, "horizontal_alignment").text = "1"
                ET.SubElement(widget, "vertical_alignment").text = "1"
                ET.SubElement(widget, "wrap_words").text = "false"
                actions = ET.SubElement(widget, "actions")
                actions.text = ""
                ET.SubElement(widget, "border_width").text = "1"

    # Input values table
    input_y = y_diff + len(pairs) * row_height + 50
    header_label = ET.SubElement(root, "widget", type="label", version="2.0.0")
    ET.SubElement(header_label, "name").text = "Header_Input"
    ET.SubElement(header_label, "text").text = "Input Values"
    ET.SubElement(header_label, "x").text = "10"
    ET.SubElement(header_label, "y").text = str(input_y - 40)
    ET.SubElement(header_label, "width").text = "360"
    ET.SubElement(header_label, "height").text = "30"
    ET.SubElement(header_label, "horizontal_alignment").text = "1"
    font = ET.SubElement(header_label, "font")
    ET.SubElement(font, "font", name="Liberation Sans", style="BOLD", size="14.0")

    for i, (name, pv) in enumerate(zip(names, pvs)):
        # Label for device name
        label = ET.SubElement(root, "widget", type="label", version="2.0.0")
        ET.SubElement(label, "name").text = f"Label_Device_{name}"
        ET.SubElement(label, "text").text = name
        ET.SubElement(label, "x").text = "10"
        ET.SubElement(label, "y").text = str(input_y)
        ET.SubElement(label, "width").text = "150"
        ET.SubElement(label, "height").text = "30"
        ET.SubElement(label, "horizontal_alignment").text = "1"
        # Textupdate for value
        widget = ET.SubElement(root, "widget", type="textupdate", version="2.0.0")
        ET.SubElement(widget, "name").text = f"TextUpdate_Input_{name}"
        ET.SubElement(widget, "pv_name").text = pv
        ET.SubElement(widget, "x").text = "170"
        ET.SubElement(widget, "y").text = str(input_y)
        ET.SubElement(widget, "width").text = "200"
        ET.SubElement(widget, "height").text = "30"
        ET.SubElement(widget, "horizontal_alignment").text = "1"
        ET.SubElement(widget, "vertical_alignment").text = "1"
        ET.SubElement(widget, "wrap_words").text = "false"
        actions = ET.SubElement(widget, "actions")
        actions.text = ""
        ET.SubElement(widget, "border_width").text = "1"
        input_y += 35

    # Update height
    final_height = input_y + 50
    ET.SubElement(root, "height").text = str(final_height)

    tree = ET.ElementTree(root)
    rough_string = ET.tostring(root, encoding='unicode')
    dom = xml.dom.minidom.parseString(rough_string)
    pretty_xml = dom.toprettyxml(indent="  ")
    # Replace the XML declaration to include encoding
    pretty_xml = pretty_xml.replace('<?xml version="1.0" ?>', '<?xml version="1.0" encoding="UTF-8"?>')
    # Remove extra newlines
    lines = pretty_xml.split('\n')
    non_empty_lines = [line for line in lines if line.strip()]
    pretty_xml = '\n'.join(non_empty_lines) + '\n'
    with open(args.bob, 'w', encoding='utf-8') as f:
        f.write(pretty_xml)
    print(f"Generated Phoebus display file: {args.bob}")

    if args.create_display_only:
        print("Display creation complete. Exiting.")
        return

    def monitor_pvs():
        def callback(pvname, value, **kwargs):
            pv_timestamp = kwargs.get('timestamp', -1) ## if no timestamp, set to -1
            print(f"Callback for {pvname}: value={value}, timestamp={pv_timestamp}")
            name = pv_to_name.get(pvname)
            if name and name in data:
                data[pvname]['times'].append(pv_timestamp)
                timestamp_pvs[name].set(pv_timestamp)
                if len(data[pvname]['times']) > 1:
                    dt = pv_timestamp - data[pvname]['times'][-2]
                    freq = 1.0 / dt if dt > 0 else 0.0
                    data[pvname]['freqs'].append(freq)
                    # Keep only recent samples
                    if len(data[pvname]['freqs']) > window_size:
                        data[pvname]['freqs'] = data[pvname]['freqs'][-window_size:]
                        data[pvname]['times'] = data[pvname]['times'][-window_size:]
                update_calculations()

        # Connect to PVs
        for pv in pvs:
            print(f"Starting to monitor {pv}")
            try:
                epics.camonitor(pv, callback=callback)
                print(f"Successfully set up monitor for {pv}")
            except Exception as e:
                print(f"Failed to monitor {pv}: {e}")

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