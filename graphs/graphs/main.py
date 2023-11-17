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
import numpy as np
import requests

def format_year(year):
    if year > 10:
        year += 2006
    return 'DBfH {}'.format(year)     

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
       
def load_previous_donations(start_end_times, donation_url_template, timeout):
        
        all_years = {}
        for year in start_end_times:
            start, end = start_end_times[year]
            if not end:
                current_year = year
                continue                
            
            url = donation_url_template.format(year, year)
            logging.info('Loading {}'.format(url))
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
        label = format_year(year)        
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
    bokeh.plotting.output_file(filename=output_path, title='DBfH All Years Donations')
    bokeh.plotting.save(p, filename=output_path)
    logging.info('{} Saved'.format(output_path))
    
def shifts_graph(start_end_times, current_year, current_json, base_dir, shifts):
    
    logging.info('Generating DBfH {} shifts graph'.format(current_year))
    times, donations = parse_json(current_json, start_end_times[current_year][0], every_five=False)
    start_hour = int(start_end_times[current_year][0][11:13])

    hours = times / 3600 + start_hour
    mod_hours = hours % 24
    n_days = int(hours.max() / 24) + 1
    
    p = bokeh.plotting.figure(x_axis_label='Hour of Day', y_axis_label='Donations', x_range=(0, 24 * 3600),
                          width=1280, height=720, active_scroll='wheel_zoom',
                          tools='pan,wheel_zoom,box_zoom,reset')
    p.add_tools(bokeh.models.HoverTool(tooltips=[('', '$name'), ('Hour of Day', '@Hours{00:00:00}'),
                                       ('Donations', '$@Donations{0,0.00}')]))
    
    for day in range(n_days):

        for shift in shifts:
            in_range = (hours >= day * 24 + shift[1]) & (hours <= day * 24 + shift[2])
            hours_in_range = mod_hours[in_range]
            if mod_hours[in_range].size:
                
                if hours_in_range[-1] == 0.:
                    hours_in_range[-1] = 24  
                model = bokeh.models.ColumnDataSource(data={'Hours':hours_in_range * 3600, 'Donations':donations[in_range] - donations[in_range][0]})
                p.line(x='Hours', y='Donations', source=model, line_color=bokeh.palettes.Category10[10][day],
                       line_width=2, legend_label='Day {}'.format(day + 1), name='Day {} {}'.format(day + 1, shift[0]))
                
    p.xaxis.ticker = bokeh.models.AdaptiveTicker(mantissas=[60, 120, 300, 600, 1200, 3600, 7200, 10800, 43200, 86400], base=10000000)
    p.xaxis.formatter = bokeh.models.NumeralTickFormatter(format='00:00:00')
    p.yaxis.formatter = bokeh.models.NumeralTickFormatter(format='$0,0')

    p.legend.location = "top_left"
    p.legend.click_policy="hide"                
    
    output_path = os.path.join(base_dir, 'DBfH_{}_shifts_graph.html'.format(current_year))
    bokeh.plotting.output_file(filename=output_path, title='{} Shift Donations'.format(format_year(current_year)))
    bokeh.plotting.save(p, filename=output_path)
    logging.info('{} Saved'.format(output_path))    


@argh.arg('--base-dir', help='Directory where graphs are output. Default is current working directory.')
def main(donation_url_template, base_dir='.'):
    
    stopping = gevent.event.Event()  
    
    logging.getLogger('bokeh').setLevel(logging.WARNING)
    
    delay = 60 * 1
    timeout = 15
    
    shifts = [['Zeta Shift',   0, 6],
              ['Alpha Flight', 6, 12],
              ['Dawn Guard',  12, 18],
              ['Night Watch', 18, 24]]
    
    # First load data required 
    logging.info('Loading start and end times')
    start_end_path = os.path.join(base_dir, 'start_end_times.json')
    start_end_times = json.load(open(start_end_path))
    start_end_times = {int(year):start_end_times[year] for year in start_end_times}
    
    all_years, current_year = load_previous_donations(start_end_times, donation_url_template, timeout)
    current_url = donation_url_template.format(current_year, current_year)

    while not stopping.is_set():

        try:

            logging.info('Loading {}'.format(current_url))
            current_json = requests.get(current_url, timeout=timeout).json()
            
            all_years_donations_graph(start_end_times, all_years, current_year, current_json, base_dir)
            
            shifts_graph(start_end_times, current_year, current_json, base_dir, shifts)


        except Exception:
            logging.exception('Plotting failed. Retrying')

        stopping.wait(delay)

