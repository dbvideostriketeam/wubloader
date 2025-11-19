import itertools
import math
import operator


def fix_chain(seconds, corrected_chains, days, subgroup, first, second):
	m = (corrected_chains[second] - corrected_chains[first]) / (seconds[second] - seconds[first])
	b = corrected_chains[first] - m * seconds[first] 
	for i in subgroup:
		if days[i] is None or days[i] == 'score':
			continue
		corrected_chains[i] = m * seconds[i] + b


def post_process_miles(seconds, miles, days):
	MAX_SPEED = 1 # chains per second
	START = 109.3 * 80 # in chains
	# convert to chains to avoid floating point issues
	chains = [math.nan if mile is None else 80 * mile for mile in miles]
	whole_miles = [math.nan if mile is None else 80 * int(mile) for mile in miles]
	
	good = []
	suspect = []
	for i in range(1, len(seconds) - 1):
		if math.isnan(chains[i]) or chains[i] < START:
			suspect.append(i)
			continue
		if days[i] is None or days[i] == 'score':
			suspect.append(i)
			continue
		# the last digit of the odometer is less reliable so throw out negative changes in the whole miles or increases of more than one mile
		previous_diff = whole_miles[i] - whole_miles[i - 1]
		if math.isnan(previous_diff) or previous_diff < 0 or previous_diff > 80:
			suspect.append(i)
			continue
		next_diff = whole_miles[i + 1] - whole_miles[i]
		if math.isnan(next_diff) or next_diff < 0 or next_diff > 80:
			suspect.append(i)
			continue			
		previous_diff = chains[i] - chains[i - 1]
		if math.isnan(previous_diff) or previous_diff < 0 or previous_diff > MAX_SPEED * (seconds[i] - seconds[i - 1]):
			suspect.append(i)
			continue
		next_diff = chains[i + 1] - chains[i]
		if math.isnan(next_diff) or next_diff < 0 or next_diff > MAX_SPEED * (seconds[i + 1] - seconds[i]):
			suspect.append(i)
			continue
		if good:
			good_diff = chains[i] - chains[good[-1]]
			time_diff = seconds[i] - seconds[good[-1]]
			# handle big jumps to apparently good data
			if good_diff > MAX_SPEED * time_diff:
				suspect.append(i)
				continue
			# the only valid reason for the milage to go down is if they crash.
			# If they have crashed, then they should have been able to reach the current milage since the earliest posible crash
			if good_diff < 0 and chains[i] > START + time_diff * MAX_SPEED:
				suspect.append(i)
				continue
		good.append(i)

	# if there are no 'good' odometer readings, bail on post processing 
	if len(good) == 0:
		return [math.nan for i in range(len(chains))]

	corrected_chains = [chains[i] if i in good else 0. for i in range(len(chains))]
	# identify groups of suspicious data and correct them
	for k, g in itertools.groupby(enumerate(suspect), lambda x:x[0]-x[1]):
		group = map(operator.itemgetter(1), g)
		group = list(map(int, group))
		to_fix = []
		for i in group:
			back = 1
			# check whether any suspicious data is likely valid and mark it as not suspicious
			while True:
				if corrected_chains[i - back]:
					diff = chains[i] - corrected_chains[i - back]
					max_diff = MAX_SPEED * (seconds[i] - seconds[i - back])
					forward_diff = chains[group[-1] + 1] - chains[i]
					forward_max_diff = MAX_SPEED * (seconds[group[-1] + 1] - seconds[i])
					if diff >= 0 and diff <= max_diff and forward_diff <= forward_max_diff:
						corrected_chains[i] = chains[i]
					break
				else:
					back += 1
			if not corrected_chains[i]:
				to_fix.append(i)

		# actually fix remaining suspicious data via linear interpolation
		for k, g in itertools.groupby(enumerate(to_fix), lambda x:x[0]-x[1]):
			subgroup = map(operator.itemgetter(1), g)
			subgroup = list(map(int, subgroup))
			# ignore data from before the first good measurement or after crashes
			if subgroup[0] < good[0] or corrected_chains[subgroup[0] - 1] > corrected_chains[subgroup[-1] + 1]:
				continue
			fix_chain(seconds, corrected_chains, days, subgroup, subgroup[0] - 1, subgroup[-1] + 1)
	
	to_fix = []
	# custom handling of the start
	for earliest in range(len(seconds)):
		if corrected_chains[earliest]:
			break
	for i in range(earliest - 1, -1, -1):
		foreward = 1
		while True:
			if corrected_chains[i + foreward]:
				diff = corrected_chains[i + foreward] - chains[i]
				max_diff = MAX_SPEED * (seconds[i + foreward] - seconds[i])
				if diff >= 0 and diff <= max_diff:
					corrected_chains[i] = chains[i]
				break
			else:
				foreward += 1

		if not corrected_chains[i]:
			to_fix.append(i)
	to_fix = to_fix[::-1]
			
	# custom handling of the end
	# find the most recent good value
	for latest in range(len(seconds) - 1, -1, -1):
		if corrected_chains[latest]:
			break
	for i in range(latest + 1, len(seconds)):
		back = 1
		while True:
			if corrected_chains[i - back]:
				diff = chains[i] - corrected_chains[i - back]
				max_diff = MAX_SPEED * (seconds[i] - seconds[i - back])
				if diff >= 0 and diff <= max_diff:
					corrected_chains[i] = chains[i]
				break
			else:
				back += 1
		if not corrected_chains[i]:
			to_fix.append(i)
	
	# linear interpolation to fix gaps near but not at start and end
	for k, g in itertools.groupby(enumerate(to_fix), lambda x:x[0]-x[1]):
		subgroup = map(operator.itemgetter(1), g)
		subgroup = list(map(int, subgroup))
		# ignore the last data point or after crashes, or ranges at the very start or end
		if subgroup[0] == 0 or subgroup[-1] == (len(corrected_chains) - 1) or corrected_chains[subgroup[0] - 1] > corrected_chains[subgroup[-1] + 1]:
			continue
		fix_chain(seconds, corrected_chains, days, subgroup, subgroup[0] - 1, subgroup[-1] + 1)
	# special handling of the end
	if not corrected_chains[-1]:
		for latest in range(len(seconds) - 1, -1, -1):
			if corrected_chains[latest]:
				break
		if corrected_chains[latest - 1]:
			subgroup = range(latest + 1, len(seconds))
			fix_chain(seconds, corrected_chains, days, subgroup, latest - 1, latest)
	# and of the start
	if not corrected_chains[0]:
		for earliest in range(len(seconds)):
			if corrected_chains[earliest]:
				break
		if corrected_chains[earliest + 1]:
			subgroup = range(earliest)
			fix_chain(seconds, corrected_chains, days, subgroup, earliest, earliest + 1)

	corrected_miles = [chain / 80 if chain > 0 else None for chain in corrected_chains]
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
