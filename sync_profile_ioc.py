#!/usr/bin/env python3

import argparse
import time
import threading
import numpy as np
import logging
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
    parser.add_argument("--polling-freq", type=float, help="Polling frequency in Hz, if not given use monitoring")
    parser.add_argument("--iocname", help="IOC name to display as title")
    parser.add_argument("--loglevel", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level")
    parser.add_argument("--create-display-only", action="store_true", help="Create Phoebus display file and exit without running IOC")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.loglevel.upper()), format='%(asctime)s - %(levelname)s - %(message)s')

    with open(args.config) as f:
        config = yaml.safe_load(f)
    devices = config['devices']
    names = [d['name'] for d in devices]
    pvs = [d['pv'] for d in devices]
    name_to_pv = {d['name']: d['pv'] for d in devices}
    pv_to_name = {d['pv']: d['name'] for d in devices}

    logging.info(f"Loaded {len(devices)} devices from {args.config}")
    logging.info("Monitoring PVs:")
    for name, pv in zip(names, pvs):
        logging.info(f"  {name}: {pv}")
    logging.info(f"IOC prefix: {args.prefix}")
    logging.info(f"Output PV list file: {args.pvout}")
    if args.polling_freq:
        logging.info(f"Mode: Polling at {args.polling_freq} Hz")
    else:
        logging.info("Mode: Monitoring")

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
            'instant': builder.aIn(f'{name}:InstantFreq', initial_value=0.0, PREC=6),
            'avg': builder.aIn(f'{name}:AvgFreq', initial_value=0.0, PREC=6),
            'min': builder.aIn(f'{name}:MinFreq', initial_value=0.0, PREC=6),
            'max': builder.aIn(f'{name}:MaxFreq', initial_value=0.0, PREC=6),
            'std': builder.aIn(f'{name}:StdFreq', initial_value=0.0, PREC=6),
        }
        timestamp_pvs[name] = builder.aIn(f'{name}:Timestamp', initial_value=0.0, PREC=6)

    # Create PVs for time diffs between PVs
    diff_pvs = {}
    for i in range(num_pvs):
        for j in range(i+1, num_pvs):
            name1 = names[i]
            name2 = names[j]
            pair_name = f'{name1}_vs_{name2}'
            diff_pvs[(i, j)] = {
                'current': builder.aIn(f'{pair_name}:CurrentDiff', initial_value=0.0, PREC=6),
                'avg': builder.aIn(f'{pair_name}:AvgDiff', initial_value=0.0, PREC=6),
                'min': builder.aIn(f'{pair_name}:MinDiff', initial_value=0.0, PREC=6),
                'max': builder.aIn(f'{pair_name}:MaxDiff', initial_value=0.0, PREC=6),
                'std': builder.aIn(f'{pair_name}:StdDiff', initial_value=0.0, PREC=6),
            }

    logging.info("Created output PVs:")
    for name in names:
        logging.info(f"  Stats for {name}: {args.prefix}:{name}:Timestamp, InstantFreq, AvgFreq, MinFreq, MaxFreq, StdFreq")
    for i in range(num_pvs):
        for j in range(i+1, num_pvs):
            name1 = names[i]
            name2 = names[j]
            pair_name = f'{name1}_vs_{name2}'
            logging.info(f"  Time diff stats for {name1} vs {name2}: {args.prefix}:{pair_name}:CurrentDiff, AvgDiff, MinDiff, MaxDiff, StdDiff")

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
    display_name = args.iocname if args.iocname else "Sync Profile"
    ET.SubElement(root, "name").text = display_name
    mode_text = "Mode: Monitoring"
    if args.polling_freq:
        mode_text = f"Mode: Polling at {args.polling_freq} Hz"
    column_width = 120
    x_start = 10
    y_start = 80  # Increased to leave more space after mode label
    row_height = 35
    columns_device = ['Device', 'Timestamp', 'InstantFreq', 'AvgFreq', 'MinFreq', 'MaxFreq', 'StdFreq']
    widths_device = [180, 120, 120, 120, 120, 120, 120]
    width = x_start + sum(widths_device)  # for device table
    height = 1000  # approximate, will adjust
    ET.SubElement(root, "width").text = str(width)
    ET.SubElement(root, "height").text = str(height)
    actions = ET.SubElement(root, "actions")
    actions.text = ""
    # Add title label first
    title_label = ET.SubElement(root, "widget", type="label", version="2.0.0")
    ET.SubElement(title_label, "name").text = "Title_Label"
    ET.SubElement(title_label, "text").text = display_name
    ET.SubElement(title_label, "x").text = "10"
    ET.SubElement(title_label, "y").text = "10"
    ET.SubElement(title_label, "width").text = str(width)
    ET.SubElement(title_label, "height").text = "30"
    ET.SubElement(title_label, "horizontal_alignment").text = "1"
    ET.SubElement(title_label, "background_color").text = "#F0F0F0"
    ET.SubElement(title_label, "foreground_color").text = "#0000FF"
    font = ET.SubElement(title_label, "font")
    ET.SubElement(font, "font", name="Liberation Sans", style="BOLD", size="26.0")
    # Add mode label after
    mode_label = ET.SubElement(root, "widget", type="label", version="2.0.0")
    ET.SubElement(mode_label, "name").text = "Mode_Label"
    ET.SubElement(mode_label, "text").text = mode_text
    ET.SubElement(mode_label, "x").text = "10"
    ET.SubElement(mode_label, "y").text = "40"
    ET.SubElement(mode_label, "width").text = "400"
    ET.SubElement(mode_label, "height").text = "25"
    ET.SubElement(mode_label, "horizontal_alignment").text = "0"
    ET.SubElement(mode_label, "background_color").text = "#E8F4FD"  # Light blue background
    font = ET.SubElement(mode_label, "font")
    ET.SubElement(font, "font", name="Liberation Sans", style="BOLD", size="14.0")

    # Device stats table
    y = y_start
    for col_idx, col in enumerate(columns_device):
        width_col = widths_device[col_idx]
        x = x_start + sum(widths_device[:col_idx])
        # Column label
        label = ET.SubElement(root, "widget", type="label", version="2.0.0")
        ET.SubElement(label, "name").text = f"Label_Device_{col}"
        ET.SubElement(label, "text").text = col
        ET.SubElement(label, "x").text = str(x)
        ET.SubElement(label, "y").text = "65"  # Adjusted y
        ET.SubElement(label, "width").text = str(width_col - 10)
        ET.SubElement(label, "height").text = "30"
        ET.SubElement(label, "horizontal_alignment").text = "1"
        ET.SubElement(label, "background_color").text = "#D3D3D3"  # Light gray
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
                ET.SubElement(dev_label, "width").text = str(width_col - 10)
                ET.SubElement(dev_label, "height").text = "30"
                ET.SubElement(dev_label, "horizontal_alignment").text = "1"
            else:
                pv = f"{args.prefix}:{name}:{col}"
                widget = ET.SubElement(root, "widget", type="textupdate", version="2.0.0")
                ET.SubElement(widget, "name").text = f"TextUpdate_{name}_{col}"
                ET.SubElement(widget, "pv_name").text = pv
                ET.SubElement(widget, "x").text = str(x)
                ET.SubElement(widget, "y").text = str(yy)
                ET.SubElement(widget, "width").text = str(width_col - 10)
                ET.SubElement(widget, "height").text = "30"
                ET.SubElement(widget, "horizontal_alignment").text = "1"
                ET.SubElement(widget, "vertical_alignment").text = "1"
                ET.SubElement(widget, "wrap_words").text = "false"
                ET.SubElement(widget, "precision").text = "6"
                actions = ET.SubElement(widget, "actions")
                actions.text = ""
                ET.SubElement(widget, "border_width").text = "1"

    # Diff stats table
    y_diff = y + len(names) * row_height + 50
    columns_diff = ['Pair', 'CurrentDiff', 'AvgDiff', 'MinDiff', 'MaxDiff', 'StdDiff']
    widths_diff = [180, 120, 120, 120, 120, 120]
    for col_idx, col in enumerate(columns_diff):
        width_col = widths_diff[col_idx]
        x = x_start + sum(widths_diff[:col_idx])
        # Column label
        label = ET.SubElement(root, "widget", type="label", version="2.0.0")
        ET.SubElement(label, "name").text = f"Label_Diff_{col}"
        ET.SubElement(label, "text").text = col
        ET.SubElement(label, "x").text = str(x)
        ET.SubElement(label, "y").text = str(y_diff - 30)
        ET.SubElement(label, "width").text = str(width_col - 10)
        ET.SubElement(label, "height").text = "30"
        ET.SubElement(label, "horizontal_alignment").text = "1"
        ET.SubElement(label, "background_color").text = "#D3D3D3"
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
                ET.SubElement(pair_label, "width").text = str(width_col - 10)
                ET.SubElement(pair_label, "height").text = "30"
                ET.SubElement(pair_label, "horizontal_alignment").text = "1"
            else:
                pv = f"{args.prefix}:{pair}:{col}"
                widget = ET.SubElement(root, "widget", type="textupdate", version="2.0.0")
                ET.SubElement(widget, "name").text = f"TextUpdate_{pair}_{col}"
                ET.SubElement(widget, "pv_name").text = pv
                ET.SubElement(widget, "x").text = str(x)
                ET.SubElement(widget, "y").text = str(yy)
                ET.SubElement(widget, "width").text = str(width_col - 10)
                ET.SubElement(widget, "height").text = "30"
                ET.SubElement(widget, "horizontal_alignment").text = "1"
                ET.SubElement(widget, "vertical_alignment").text = "1"
                ET.SubElement(widget, "wrap_words").text = "false"
                ET.SubElement(widget, "precision").text = "6"
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
    ET.SubElement(header_label, "background_color").text = "#D3D3D3"
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
        ET.SubElement(widget, "precision").text = "6"
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
    logging.info(f"Generated Phoebus display file: {args.bob}")

    with open(args.bob, 'w', encoding='utf-8') as f:
        f.write(pretty_xml)

    if args.create_display_only:
        logging.info("Display creation complete. Exiting.")
        return

    def monitor_pvs():
        def process_update(pvname, value, pv_timestamp):
            name = pv_to_name.get(pvname)
            logging.debug(f"name = {name}")
            if name and pvname in data:
                data[pvname]['times'].append(pv_timestamp)
                logging.debug(f"Setting timestamp for {name} to {pv_timestamp}")
                timestamp_pvs[name].set(pv_timestamp)
                if len(data[pvname]['times']) > 1:
                    dt = pv_timestamp - data[pvname]['times'][-2]
                    freq = 1.0 / dt if dt > 0 else 0.0
                    logging.debug(f"Calculated freq for {name}: dt={dt}, freq={freq}")
                    data[pvname]['freqs'].append(freq)
                    # Keep only recent samples
                    if len(data[pvname]['freqs']) > window_size:
                        data[pvname]['freqs'] = data[pvname]['freqs'][-window_size:]
                        data[pvname]['times'] = data[pvname]['times'][-window_size:]
                update_calculations()

        if args.polling_freq:
            # Polling mode
            polling_interval = 1.0 / args.polling_freq
            pv_objects = [epics.PV(pv) for pv in pvs]
            while True:
                for pv_obj in pv_objects:
                    try:
                        value = pv_obj.get()
                        timestamp = pv_obj.timestamp
                        process_update(pv_obj.pvname, value, timestamp)
                    except Exception as e:
                        logging.error(f"Failed to poll {pv_obj.pvname}: {e}")
                time.sleep(polling_interval)
        else:
            # Monitoring mode
            def callback_monitor(pvname, value, **kwargs):
                pv_timestamp = kwargs.get('timestamp', -1)
                process_update(pvname, value, pv_timestamp)

            # Connect to PVs
            for pv in pvs:
                logging.info(f"Starting to monitor {pv}")
                try:
                    epics.camonitor(pv, callback=callback_monitor)
                    logging.info(f"Successfully set up monitor for {pv}")
                except Exception as e:
                    logging.error(f"Failed to monitor {pv}: {e}")

            # Keep running
            while True:
                time.sleep(1)

    def update_calculations():
        # Update frequency stats for each PV
        for name in names:
            pv = name_to_pv[name]
            freqs = data[pv]['freqs']
            logging.debug(f"Updating calculations for {name}, freqs = {freqs}")
            if freqs:
                instant_freq = freqs[-1]
                avg_freq = np.mean(freqs)
                min_freq = np.min(freqs)
                max_freq = np.max(freqs)
                std_freq = np.std(freqs)

                logging.debug(f"Setting {args.prefix}:{name}:InstantFreq = {instant_freq}")
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