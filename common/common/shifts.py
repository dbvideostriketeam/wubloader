
import datetime

from common import dateutil
from common.requests import InstrumentedSession

UTC = datetime.timezone.utc
requests = InstrumentedSession()


def parse_shift_time(time_str, timeout=5):
    """Parse times in the shift definition.
        
       The parser first tries to parse a string as a datetime before trying the string as a URL to fetch a timestamp from."""
    if not time_str:
        return None
    try:
        return dateutil.parse(time_str)
    except ValueError:
        try:
            resp = requests.get(time_str, timeout=timeout, metric_name='get_shift_time')
            resp.raise_for_status()
            return dateutil.parse(resp.text.strip())
        except Exception:
            return None


def parse_shifts(shifts):
    """Parse a shifts definition

       The shifts definition is two entry mappable with two keys, repeating and one-off.

       The repeating shifts entry is a list of shift definition. Each of these is a sequence consisting of the name of the shift, the starting hour of the shift in local time, and the ending hour in local time. Repeating shifts extending across midnight can be handled by using two shifts with the same name. For example:
        [['Night', 0, 6],
         ['Day', 6, 18],
         ['Night', 18, 24]]

       The one-off shifts entry is a list of shift definitions. Each of these is a sequence consisting of the name of the shift, the start the shift, and the end of the shift. A start or end time can be a timestamp, a URL or None. If it is a URL, the URL will be queried for a timestamp. If no timezone info is provided the timestamp will be assumed to be UTC. If the start time is None, then the start will be assumed to be the earliest possible datetime; if the end is None, it will be assumed to be the oldest possible datetime. If both the start and end are None, the shift will be ignored. For example:
        [['Full', '2024-01-01T00:00:00', '2024-01-02T00:00:00'],
         ['End Only', '2024-01-02T00:00:00', None],
         ['URL', 'http://example.com/start.html', '2024-01-01T00:00:00'],
         ['Both None', None, None]]
        would be parsed as:
        [['Full', '2024-01-01T00:00:00', '2024-01-02T00:00:00'],
         ['Start Only', '2024-01-02T00:00:00', '9999-12-31T23:59:59.999999'],
         ['URL', '2023-12-31T12:00:00', '2024-01-01T00:00:00']]
         """
    new_shifts = {'repeating':shifts['repeating'], 'one_off':[]}
    for shift in shifts['one_off']:
        name, start, end = shift
        start = parse_shift_time(start)
        end = parse_shift_time(end)
        if (start is None) and (end is None):
            continue
        if start is None:
            start = datetime.datetime.min
        if end is None:
            end = datetime.datetime.max
        new_shifts['one_off'].append([name, start, end])       
    return new_shifts


def calculate_shift(time, shifts, timezone):
    """Calculate what shift a time falls in. 
        
       time is a datetime, shifts the output from parse_shifts and timezone a 
    """
    if not time:
        return ''
    
    for shift in shifts['one_off']:
        print(time, shift[1], shift[2])
        if shift[1] <= time < shift[2]:
            return shift[0]
        
    #since shifts are based on local times we have to worry about timezones for once
    local_time = time.replace(tzinfo=UTC).astimezone(timezone)
    # do a more involved calculation to allow for non-integer start and end hours
    time_diff = local_time - datetime.datetime(local_time.year, local_time.month, local_time.day, tzinfo=timezone)
    hour = time_diff / datetime.timedelta(hours=1)
    for shift in shifts['repeating']:
        if shift[1] <= hour < shift[2]:
            return shift[0]
