import datetime
import itertools
import json
import math
import operator

import argh
import base64
import flask
import gevent
import gevent.backdoor
from gevent.pywsgi import WSGIServer

import common
from common import database
from common.flask_stats import request_stats, after_request

app = flask.Flask('bus_synthesizer')
app.after_request(after_request)

MAX_SPEED = 45 / 3600

def cors(app):
	"""WSGI middleware that sets CORS headers"""
	HEADERS = [
		("Access-Control-Allow-Credentials", "false"),
		("Access-Control-Allow-Headers", "*"),
		("Access-Control-Allow-Methods", "GET,POST,HEAD"),
		("Access-Control-Allow-Origin", "*"),
		("Access-Control-Max-Age", "86400"),
	]
	def handle(environ, start_response):
		def _start_response(status, headers, exc_info=None):
			headers += HEADERS
			return start_response(status, headers, exc_info)
		return app(environ, _start_response)
	return handle


def post_process_miles(seconds, miles, days):
	good = []
	suspect = []
	for i in range(1, len(seconds) - 1):
		if math.isnan(miles[i]) or miles[i] <= 100:
			suspect.append(i)
			continue
		if days[i] is None or days[i] == 'score':
			suspect.append(i)
			continue
		previous_diff = miles[i] - miles[i - 1]
		if previous_diff < 0 or previous_diff > MAX_SPEED * (seconds[i] - seconds[i - 1]):
			suspect.append(i)
			continue
		next_diff = miles[i + 1] - miles[i]
		if next_diff < 0 or next_diff > MAX_SPEED * (seconds[i + 1] - seconds[i]):
			suspect.append(i)
			continue
		# handle big jumps to apparently good data
		if good and miles[i] - miles[good[-1]] > MAX_SPEED * (seconds[i] - seconds[good[-1]]):
			suspect.append(i)
			continue
		# try to filter out bad data at the start
		if not good and miles[i] > 1000:
			suspect.append(i)
			continue
		good.append(i)

	corrected_miles = [miles[i] if i in good else 0. for i in range(len(miles))]
	# identify groups of suspicious data and correct them
	for k, g in itertools.groupby(enumerate(suspect), lambda x:x[0]-x[1]):
		group = map(operator.itemgetter(1), g)
		group = list(map(int, group))
		to_fix = []
		for i in group:
			back = 1
			# check whether any suspicious data is likely valid and mark it as not suspicious
			while True:
				if corrected_miles[i - back]:
					diff = miles[i] - corrected_miles[i - back]
					max_diff = MAX_SPEED * (seconds[i] - seconds[i - back])
					forward_diff = miles[group[-1] + 1] - miles[i]
					forward_max_diff = MAX_SPEED * (seconds[group[-1] + 1] - seconds[i])
					if diff >= 0 and diff <= max_diff and forward_diff <= forward_max_diff:
						corrected_miles[i] = miles[i]
					break
				else:
					back += 1
			if not corrected_miles[i]:
				to_fix.append(i)

		# actually fix remaining suspicious data via linear interpolation
		for k, g in itertools.groupby(enumerate(to_fix), lambda x:x[0]-x[1]):
			subgroup = map(operator.itemgetter(1), g)
			subgroup = list(map(int, subgroup))
			# ignore data from before the first good measurement or after crashes
			if subgroup[0] < good[0] or corrected_miles[subgroup[0] - 1] > corrected_miles[subgroup[-1] + 1]:
				continue
			m = (corrected_miles[subgroup[-1] + 1] - corrected_miles[subgroup[0] - 1]) / (seconds[subgroup[-1] + 1] - seconds[subgroup[0] - 1])
			b = corrected_miles[subgroup[-1] + 1] - m * seconds[subgroup[-1] + 1]	   
			for i in subgroup:
				corrected_miles[i] = m * seconds[i] + b

	# custom handling of the start and end
	if 0 <= corrected_miles[1] - miles[0] <= MAX_SPEED * (seconds[1] - seconds[0]):
		corrected_miles[0] = miles[0]
	if 0 <= miles[-1] - corrected_miles[-2] <= MAX_SPEED * (seconds[-1] - seconds[-2]):
		corrected_miles[-1] = miles[-1]
	
	corrected_miles = [mile if mile > 0 else math.nan for mile in corrected_miles]
	return corrected_miles

@app.route('/bus_synthesizer/latest')
@request_stats
def latest(): 
	ago_30_min = datetime.datetime.utcnow() - datetime.timedelta(minutes=30)	
	query = common.database.query(app.db_manager.get_conn(), """
		SELECT timestamp, odometer, timeofday
		FROM bus_data
		WHERE timestamp > %(start)s
		--AND NOT segment LIKE '%%partial%%'
		ORDER BY timestamp;
		""", start=ago_30_min)
	rows = query.fetchall()
	times, miles, days = zip(*rows)
	
	seconds = [(time - times[0]) / datetime.timedelta(seconds=1) for time in times]
	miles = [math.nan if mile is None else mile for mile in miles]
	corrected_miles = post_process_miles(seconds, miles, days)
	
	raw = times[-1], miles[-1], days[-1]
	
	latest = None
	second_latest = None
	for i in range(len(times) - 1, -1, -1):
		if not math.isnan(corrected_miles[i]):
			if latest is None:
				latest = times[i], seconds[i], corrected_miles[i], days[i]
			elif second_latest is None:
				second_latest = times[i], seconds[i], corrected_miles[i], days[i]
			else:
				break
				
	if latest is not None:
		processed = latest[0], latest[2], latest[3]
	else:
		processed = (None, None, None)

	if second_latest is not None:
		m = (latest[2] - second_latest[2]) / (latest[1] - second_latest[1])
		b = latest[2] - m * latest[1]
		now = datetime.datetime.utcnow()
		now_second = (now - times[0]) / datetime.timedelta(seconds=1)
		predicted = now, m * now_second + b, days[-1]
	else:
		predicted = None, None, None
	   
	output = {'raw':tuple_to_dict(raw),
			  'post_processed':tuple_to_dict(processed),
			  'predicted':tuple_to_dict(predicted),
		     }
	return to_json(output)


def tuple_to_dict(t, names=['time', 'mile', 'ToD']):
	return {names[i]:t[i] for i in range(len(t))}


# copied from thrimshim
def to_json(obj):
	def convert(value):
		if isinstance(value, datetime.datetime):
			return value.isoformat()
		if isinstance(value, datetime.timedelta):
			return value.total_seconds()
		if isinstance(value, memoryview) or isinstance(value, bytes):
			return base64.b64encode(bytes(value)).decode()
		raise TypeError(f"Can't convert object of type {value.__class__.__name__} to JSON: {value}")
	return json.dumps(obj, default=convert)


def main(connection_string, host='0.0.0.0', port=8004, backdoor_port=0):

	server = WSGIServer((host, port), cors(app))

	app.db_manager = database.DBManager(dsn=connection_string)

	common.PromLogCountsHandler.install()
	common.install_stacksampler()

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	common.serve_with_graceful_shutdown(server)
