var desertBusStart = new Date("1970-01-01T00:00:00Z");
var timeFormat = 'AGO';

pageSetup = function(isEditor) {

    //Get values from ThrimShim
    if(isEditor && /id=/.test(document.location.search)) {
        var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
        fetch("/thrimshim/"+rowId).then(data => data.json()).then(function (data) {
            if (!data) {
                alert("No video available for stream.");
                return;
            }
            desertBusStart = new Date(data.bustime_start);
            document.getElementById("VideoTitlePrefix").value = data.title_prefix;
            document.getElementById("VideoTitle").setAttribute("maxlength", data.title_max_length);

            document.getElementById("StreamName").value = data.video_channel;
            document.getElementById("hiddenSubmissionID").value = data.id;
            // for editor, switch to bustime since that's the default
            timeFormat = 'BUSTIME';
            // Apply padding - start 1min early, finish 2min late because these times are generally
            // rounded down to the minute, so if something ends at "00:10" it might actually end
            // at 00:10:59 so we should pad to 00:12:00.
            var start = (data.event_start) ? new Date(fromTimestamp(data.event_start).getTime() - 60*1000) : null;
            var end = (data.event_end) ? new Date(fromTimestamp(data.event_end).getTime() + 2*60*1000) : null;
            setTimeRange(start, end);
            // title and description both default to row description
            document.getElementById("VideoTitle").value = data.video_title ? data.video_title : data.description;
            document.getElementById("VideoDescription").value = data.video_description ? data.video_description : data.description;

            // If any edit notes, show them
            if (data.notes.length > 0) {
                document.getElementById("EditNotes").value = data.notes;
                document.getElementById("EditNotesPane").style.display = "block";
            }

            // Restore advanced options. If any of these are non-default, automatically expand the advanced options pane.
            setOptions('uploadLocation', data.upload_locations, data.upload_location);
            document.getElementById("AllowHoles").checked = data.allow_holes;
            document.getElementById("uploaderWhitelist").value = (!!data.uploader_whitelist) ? data.uploader_whitelist.join(",") : "";
            if (
                (
					data.upload_locations.length > 0
					&& data.upload_location != null
					&& data.upload_location != data.upload_locations[0]
				)
                || data.allow_holes
                || !!data.uploader_whitelist
            ) {
                document.getElementById('wubloaderAdvancedInputTable').style.display = "block";
            }

            loadPlaylist(isEditor, data.video_start, data.video_end, data.video_quality);
        });
    }
    else {
        if (isEditor) { document.getElementById('SubmitButton').disabled = true; }

        fetch("/thrimshim/defaults").then(data => data.json()).then(function (data) {
            desertBusStart = new Date(data.bustime_start);
            document.getElementById("StreamName").value = data.video_channel;
            if (isEditor) {
                document.getElementById("VideoTitlePrefix").value = data.title_prefix;
                document.getElementById("VideoTitle").setAttribute("maxlength", data.title_max_length);
                setOptions('uploadLocation', data.upload_locations);
            }

            // Default time format changes depending on mode.
            // But in both cases the default input value is 10min ago / "",
            // it's just for editor we convert it before the user sees.
            if (isEditor) {
                toggleTimeInput('BUSTIME');
            }

            loadPlaylist(isEditor);
        });

    }
};

// Time-formatting functions

parseDuration = function(duration) {
    var direction = 1;
    if(duration.startsWith("-")) {
        duration = duration.slice(1);
        direction = -1;
    }
    var parts = duration.split(':');
    return (parseInt(parts[0]) + (parts[1] || "0")/60 + (parts[2] || "0")/3600) * 60 * 60 * direction;
}

toBustime = function(date) {
    return (date < desertBusStart ? "-":"") + videojs.formatTime(Math.abs((date - desertBusStart)/1000), 600.01).padStart(7, "0:");
};

fromBustime = function(bustime) {
    return new Date(desertBusStart.getTime() + 1000 * parseDuration(bustime));
};

toTimestamp = function(date) {
    return date.toISOString().substring(0, 19);
}

fromTimestamp = function(ts) {
    return new Date(ts + "Z");
}

toAgo = function(date) {
    now = new Date()
    return (date < now ? "":"-") + videojs.formatTime(Math.abs((date - now)/1000), 600.01).padStart(7, "0:");
}

fromAgo = function(ago) {
    return new Date(new Date().getTime() - 1000 * parseDuration(ago));
}

// Set the stream start/end range from a pair of Dates using the current format
// If given null, sets to blank.
setTimeRange = function(start, end) {
    var toFunc = {
        UTC: toTimestamp,
        BUSTIME: toBustime,
        AGO: toAgo,
    }[timeFormat];
    document.getElementById("StreamStart").value = (start) ? toFunc(start) : "";
    document.getElementById("StreamEnd").value = (end) ? toFunc(end) : "";
}

// Get the current start/end range as Dates using the current format
// Returns an object containing 'start' and 'end' fields.
// If either is empty / invalid, returns null.
getTimeRange = function() {
    var fromFunc = {
        UTC: fromTimestamp,
        BUSTIME: fromBustime,
        AGO: fromAgo,
    }[timeFormat];
    var convert = function(value) {
        if (!value) { return null; }
        var date = fromFunc(value);
        return (isNaN(date)) ? null : date;
    };
    return {
        start: convert(document.getElementById("StreamStart").value),
        end: convert(document.getElementById("StreamEnd").value),
    };
}

getTimeRangeAsTimestamp = function() {
    var range = getTimeRange();
    return {
        // if not null, format as timestamp
        start: range.start && toTimestamp(range.start),
        end: range.end && toTimestamp(range.end),
    };
}

toggleHiddenPane = function(paneID) {
    var pane = document.getElementById(paneID);
    pane.style.display = (pane.style.display === "none") ? "block":"none";
}

toggleUltrawide = function() {
    var body = document.getElementsByTagName("Body")[0];
    body.classList.contains("ultrawide") ? body.classList.remove("ultrawide"):body.classList.add("ultrawide");
}

toggleTimeInput = function(toggleInput) {
    // Get times using current format, then change format, then write them back
    var range = getTimeRange();
    timeFormat = toggleInput;
    setTimeRange(range.start, range.end);
}

// For a given select input element id, add the given list of options.
// If selected is given, it should be the name of an option to select.
// Otherwise the first one is used.
setOptions = function(element, options, selected) {
    if (!selected && options.length > 0) {
        selected = options[0]
    }
    options.forEach(function(option) {
        document.getElementById(element).innerHTML += '<option value="'+option+'" '+(option==selected ? 'selected':'')+'>'+option+'</option>';
    });
}

buildQuery = function(params) {
    return Object.keys(params).filter(key => params[key] !== null).map(key =>
        encodeURIComponent(key) + '=' + encodeURIComponent(params[key])
    ).join('&');
}

loadPlaylist = function(isEditor, startTrim, endTrim, defaultQuality) {
    var playlist = "/playlist/" + document.getElementById("StreamName").value + ".m3u8";

    var range = getTimeRangeAsTimestamp();
    var queryString = buildQuery(range);

	// Preserve existing edit times
	if (player && player.trimmingControls) {
		var discontinuities = mapDiscontinuities();
		if (!startTrim) {
			startTrim = getRealTimeForPlayerTime(discontinuities, player.trimmingControls().options.startTrim).replace('Z','');
		}
		if (!endTrim) {
			endTrim = getRealTimeForPlayerTime(discontinuities, player.trimmingControls().options.endTrim).replace('Z','');
		}
	}

    setupPlayer(isEditor, playlist + '?' + queryString, startTrim, endTrim);

    //Get quality levels for advanced properties / download
    document.getElementById('qualityLevel').innerHTML = "";
    fetch('/files/' + document.getElementById('StreamName').value).then(data => data.json()).then(function (data) {
        if (!data.length) {
            console.log("Could not retrieve quality levels");
            return;
        }
        var qualityLevels = data.sort().reverse();
        setOptions('qualityLevel', qualityLevels, defaultQuality);
        if (!!defaultQuality && qualityLevels.length > 0 && defaultQuality != qualityLevels[0]) {
            document.getElementById('wubloaderAdvancedInputTable').style.display = "block";
        }
    });
};

thrimbletrimmerSubmit = function(state) {
    document.getElementById('SubmitButton').disabled = true;
    var discontinuities = mapDiscontinuities();

    var wubData = {
        video_start:getRealTimeForPlayerTime(discontinuities, player.trimmingControls().options.startTrim).replace('Z',''),
        video_end:getRealTimeForPlayerTime(discontinuities, player.trimmingControls().options.endTrim).replace('Z',''),
        video_title:document.getElementById("VideoTitle").value,
        video_description:document.getElementById("VideoDescription").value,
        allow_holes:document.getElementById('AllowHoles').checked,
        upload_location:document.getElementById('uploadLocation').value,
        video_channel:document.getElementById("StreamName").value,
        video_quality:document.getElementById('qualityLevel').options[document.getElementById('qualityLevel').options.selectedIndex].value,
        uploader_whitelist:(document.getElementById('uploaderWhitelist').value ? document.getElementById('uploaderWhitelist').value.split(','):null),
        state:state,
    };
    if (!!user) {
        wubData.token = user.getAuthResponse().id_token
    }
    console.log(wubData);
    console.log(JSON.stringify(wubData));

    //Submit to thrimshim
    var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
    fetch("/thrimshim/"+rowId, {
        method: 'POST',
        headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(wubData)
    })
    .then(response => response.text().then(text => {
        if (!response.ok) {
            var error = response.statusText + ": " + text;
            console.log(error);
            alert(error);
        } else if (state == 'EDITED') {
            // Only return to dashboard if submitted, not for save draft
            setTimeout(() => { window.location.href = '/thrimbletrimmer/dashboard.html'; }, 500);
            return
        } else {
			alert("Draft saved");
		}
        document.getElementById('SubmitButton').disabled = false;
    }));
};

thrimbletrimmerDownload = function(isEditor) {
    var range = getTimeRangeAsTimestamp();
    if (isEditor) {
        if(player.trimmingControls().options.startTrim >= player.trimmingControls().options.endTrim) {
            alert("End Time must be greater than Start Time");
            return;
        }
        var discontinuities = mapDiscontinuities();
        range.start = getRealTimeForPlayerTime(discontinuities, player.trimmingControls().options.startTrim);
        range.end = getRealTimeForPlayerTime(discontinuities, player.trimmingControls().options.endTrim);
    }

    var targetURL = "/cut/" + document.getElementById("StreamName").value +
        "/"+document.getElementById('qualityLevel').options[document.getElementById('qualityLevel').options.selectedIndex].value+".ts" +
        "?" + buildQuery({
            start: range.start,
            end: range.end,
			// In non-editor, always use rough cut. They don't have the edit controls to do
			// fine time selection anyway.
			type: (isEditor) ? (
				document.getElementById('DownloadType').options[document.getElementById('DownloadType').options.selectedIndex].value
			) : "rough",
            // Always allow holes in non-editor, accidentially including holes isn't important
            allow_holes: (isEditor) ? String(document.getElementById('AllowHoles').checked) : "true",
        });
    console.log(targetURL);
    document.getElementById('DownloadLink').href = targetURL;
	document.getElementById('DownloadLink').style.display = "";
};

thrimbletrimmerManualLink = function() {
    document.getElementById("ManualButton").disabled = true;
    var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
    var body = {link: document.getElementById("ManualLink").value};
    if (!!user) {
        body.token = user.getAuthResponse().id_token;
    }
    fetch("/thrimshim/manual-link/"+rowId, {
        method: 'POST',
        headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(body)
    })
    .then(response => response.text().then(text => {
        if (!response.ok) {
            var error = response.statusText + ": " + text;
            console.log(error);
            alert(error);
            document.getElementById("ManualButton").disabled = false;
        } else {
            alert("Manual link set to " + body.link);
            setTimeout(() => { window.location.href = '/thrimbletrimmer/dashboard.html'; }, 500);
        }
    }));
};

thrimbletrimmerResetLink = function(force) {
    var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
    if(force && !confirm(
        'Are you sure you want to reset this event? ' +
        'This will set the row back to UNEDITED and forget about any video that already may exist. ' +
        'It is intended as a last-ditch command to clear a malfunctioning cutter, ' +
        'or if a video needs to be re-edited and replaced. ' +
        'IT IS YOUR RESPONSIBILITY TO DEAL WITH ANY VIDEO THAT MAY HAVE ALREADY BEEN UPLOADED. '
    )) {
        return;
    }
    document.getElementById("ResetButton").disabled = true;
    document.getElementById("CancelButton").disabled = true;
    var body = {}
    if (!!user) {
        body.token = user.getAuthResponse().id_token;
    }
    fetch("/thrimshim/reset/"+rowId + "?force=" + force, {
        method: 'POST',
        headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(body)
    })
    .then(response => response.text().then(text => {
        if (!response.ok) {
            var error = response.statusText + ": " + text;
            console.log(error);
            alert(error);
            document.getElementById("ResetButton").disabled = false;
			document.getElementById("CancelButton").disabled = true;
        } else {
            alert("Row has been " + ((force) ? "reset" : "cancelled") +". Reloading...");
            setTimeout(() => { window.location.reload(); }, 500);
        }
    }));
};
