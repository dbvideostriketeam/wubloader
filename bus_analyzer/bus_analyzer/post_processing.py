import itertools
import math
import operator

MAX_SPEED = 45 / 3600


def post_process_miles(seconds, miles, days):
	miles = [math.nan if mile is None else mile for mile in miles]
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
		if math.isnan(previous_diff) or previous_diff < 0 or previous_diff > MAX_SPEED * (seconds[i] - seconds[i - 1]):
			suspect.append(i)
			continue
		next_diff = miles[i + 1] - miles[i]
		if math.isnan(next_diff) or next_diff < 0 or next_diff > MAX_SPEED * (seconds[i + 1] - seconds[i]):
			suspect.append(i)
			continue
		# handle big jumps to apparently good data
		if good and miles[i] - miles[good[-1]] > MAX_SPEED * (seconds[i] - seconds[good[-1]]):
			suspect.append(i)
			continue
		good.append(i)

	# if there are no 'good' odometer readings, bail on post processing 
	if len(good) == 0:
		return [math.nan for i in range(len(miles))]

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

	# custom handling of the start
	if 0 <= corrected_miles[1] - miles[0] <= MAX_SPEED * (seconds[1] - seconds[0]):
		corrected_miles[0] = miles[0]

	# custom handling of the end
	# find the most recent good value
	for latest in range(len(seconds) - 1, -1, -1):
		if corrected_miles[latest]:
			break
	to_fix = []
	for i in range(latest + 1, len(seconds)):
		back = 1
		while True:
			if corrected_miles[i - back]:
				diff = miles[i] - corrected_miles[i - back]
				max_diff = MAX_SPEED * (seconds[i] - seconds[i - back])
				if diff >= 0 and diff <= max_diff:
					corrected_miles[i] = miles[i]
				break
			else:
				back += 1
		if not corrected_miles[i]:
			to_fix.append(i)

	# linear interpolation of the end 
	for k, g in itertools.groupby(enumerate(to_fix), lambda x:x[0]-x[1]):
		subgroup = map(operator.itemgetter(1), g)
		subgroup = list(map(int, subgroup))
		# ignore the last data point or after crashes
		if subgroup[-1] == (len(corrected_miles) - 1) or corrected_miles[subgroup[0] - 1] > corrected_miles[subgroup[-1] + 1]:
			continue
		m = (corrected_miles[subgroup[-1] + 1] - corrected_miles[subgroup[0] - 1]) / (seconds[subgroup[-1] + 1] - seconds[subgroup[0] - 1])
		b = corrected_miles[subgroup[-1] + 1] - m * seconds[subgroup[-1] + 1] 
		for i in subgroup:
			corrected_miles[i] = m * seconds[i] + b

	corrected_miles = [mile if mile > 0 else None for mile in corrected_miles]
	return corrected_miles


def post_process_clocks(seconds, clocks, days):
	clocks = [math.nan if clock is None else clock for clock in clocks]
	good = []
	for i in range(1, len(seconds) - 2):
		if math.isnan(clocks[i]) or clocks[i] < 60 or clocks[i] > 780:
			continue
		if days[i] is None or days[i] == 'score':
			continue
		# handle big jumps to apparently good data
		if good and (seconds[i] - seconds[good[-1]] < 120):
			if clocks[i] - clocks[good[-1]] > math.ceil((seconds[i] - seconds[good[-1]]) / 60):
				continue
			if clocks[i] - clocks[good[-1]] < math.floor((seconds[i] - seconds[good[-1]]) / 60):
				continue
		if (clocks[i] - clocks[i - 1]) in [0, 1] and (clocks[i + 1] - clocks[i]) in [0, 1]:
			good.append(i)

	corrected_clocks = [clocks[i] if i in good else 0. for i in range(len(clocks))]
	for i in range(len(seconds)):
		if corrected_clocks[i]:
			continue
		if days[i] is None or days[i] == 'score':
			continue
		for j in range(i):
			if 59.5 <= (seconds[i] - seconds[j]) <= 60.5:
				if corrected_clocks[j]:
					corrected_clocks[i] = corrected_clocks[j] + 1
				break

	return corrected_clocks
