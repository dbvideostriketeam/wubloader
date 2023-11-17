import gevent.monkey
gevent.monkey.patch_all()

import datetime
import logging
import json
import os

import argh
import bokeh.plotting
import bokeh.models
import bokeh.palettes
import bokeh.settings
import requests


import numpy as np

def parse_json(json_donations, start_date, end_hour=np.inf, every_five=True):

    end_hour = float(end_hour)
    times = []
    donations = []
    for entry in json_donations:
        times.append(datetime.datetime(*entry[:5]).isoformat())
        donations.append(entry[5])

    times = np.array(times, dtype=np.datetime64)
    donations = np.asarray(donations)

    start_time = np.datetime64(start_date)
    bustimes = np.array(times - start_time, dtype=np.int_)
    
    trimmed_bustimes = bustimes[(bustimes <= 60 * 60 * end_hour) & (bustimes >= 0)]
    trimmed_donations = donations[(bustimes <= 60 * 60 * end_hour) & (bustimes >= 0)]

    if every_five:
        five_bustimes = trimmed_bustimes[::5]
        five_donations = trimmed_donations[::5]
        return five_bustimes, five_donations
    else:
        return trimmed_bustimes, trimmed_donations
       
def load_previous_donations(start_end_times, timeout):
        
        all_years = {}
        for year in start_end_times:
            start, end = start_end_times[year]
            if not end:
                current_year = year
                continue
                
            logging.info('Loading year {}'.format(year))
            url = 'https://vst.ninja/DB{}/graphs/jsons/DB{}.json'.format(year, year)
            year_json = requests.get(url, timeout=timeout).json()
            all_years[year] = parse_json(year_json, start, end, year >= 5)
            
        return all_years, current_year
    
def all_years_donations_graph(start_end_times, all_years, current_year, current_json, base_dir):
    
    logging.info('Generating all years donation graph')
    p = bokeh.plotting.figure(x_axis_label='Bus Time', y_axis_label='Donations', x_range=(0, 60 * 60 * 172),
                              width=1280, height=720, active_scroll='wheel_zoom',
                              tools='pan,wheel_zoom,box_zoom,reset')

    p.add_tools(bokeh.models.HoverTool(tooltips=[('', '$name'), ('Bustime', '@Bustime{00:00:00}'),
                                                 ('Donations', '$@Donations{0,0.00}')]))
    for year in start_end_times:
        label_year = year
        if year > 10:
            label_year += 2006
        label = 'DBfH {}'.format(label_year)        
        if year != current_year:
            times, donations = all_years[year]
            line_width = 2
        else:
            times, donations = parse_json(current_json, start_end_times[year][0], every_five=False)
            line_width = 3
        model = bokeh.models.ColumnDataSource(data={'Bustime':times, 'Donations':donations})
        p.line(x='Bustime', y='Donations', source=model, line_width=line_width,
               line_color=bokeh.palettes.Category20[20][current_year - year],
               legend_label=label, name=label)


    p.xaxis.ticker = bokeh.models.AdaptiveTicker(mantissas=[60, 120, 300, 600, 1200, 3600, 7200, 10800, 43200, 86400], base=10000000)
    p.xaxis.formatter = bokeh.models.NumeralTickFormatter(format='00:00:00')
    p.yaxis.formatter = bokeh.models.NumeralTickFormatter(format='$0,0')

    p.legend.location = "top_left"
    p.legend.click_policy="hide"

    output_path = os.path.join(base_dir, 'all_years_donations.html')
    bokeh.settings.settings.py_log_level = 'warn'
    bokeh.plotting.output_file(filename=output_path, title='DBfH All Years Donations')
    bokeh.plotting.save(p, filename=output_path)
    logging.info('{} Saved'.format(output_path))    


@argh.arg('--base-dir', help='Directory where segments are stored. Default is current working directory.')
def main(base_dir='.'):
    
    stopping = gevent.event.Event()  
    
    logging.getLogger('bokeh').setLevel(logging.WARNING)
    
    delay = 60 * 1
    timeout = 15 
    
    # First load data required 
    logging.info('Loading start and end times')
    start_end_path = os.path.join(base_dir, 'start_end_times.json')
    start_end_times = json.load(open(start_end_path))
    start_end_times = {int(year):start_end_times[year] for year in start_end_times}
    
    all_years, current_year = load_previous_donations(start_end_times, timeout)
    current_url = 'http://example.com/{}/{}'.format(current_year, current_year)

    while not stopping.is_set():

        try:

            logging.info('Loading current data')
            current_json = requests.get(current_url, timeout=timeout).json()
            
            all_years_donations_graph(start_end_times, all_years, current_year, current_json, base_dir)


        except Exception:
            logging.exception('Plotting failed. Retrying')

        stopping.wait(delay)    

#     logging.info('Starting Graph Generator')
#     generator = GraphGenerator(current_url, start_time, previous_years:)
#     manager = gevent.spawn(generator.run)

#     def stop():
#         manager.stop()

#     gevent.signal_handler(signal.SIGTERM, stop)

#     stop()
#     logging.info('Gracefully stopped')

