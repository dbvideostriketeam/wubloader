var desertBusStart = new Date("1970-01-01T00:00:00Z");

pageSetup = function() {
    //Get values from ThrimShim
    if(/id=/.test(document.location.search)) {
        var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
        fetch("/thrimshim/"+rowId).then(data => data.json()).then(function (data) {
            if (!data) {
                alert("No video available for stream.");
                return;
            }
            desertBusStart = new Date(data.bustime_start);
            document.getElementById("VideoTitlePrefix").value = data.title_prefix;
            document.getElementById("VideoTitle").setAttribute("maxlength", data.title_max_length);

            document.getElementById("hiddenSubmissionID").value = data.id;
            document.getElementById("StreamName").value = data.video_channel ? data.video_channel:document.getElementById("StreamName").value;
            // set stream start/end, then copy to bustime inputs
            document.getElementById("StreamStart").value = data.event_start;
            document.getElementById("StreamEnd").value = data.event_end;
            setBustimeRange();
            // title and description both default to row description
            document.getElementById("VideoTitle").value = data.video_title ? data.video_title : data.description;
            document.getElementById("VideoDescription").value = data.video_description ? data.video_description : data.description;

            setOptions('uploadLocation', data.upload_locations);

            loadPlaylist(data.video_start, data.video_end);
        });
    }
    else {
        document.getElementById('SubmitButton').disabled = true;

        var startOfHour = new Date(new Date().setMinutes(0,0,0));
        document.getElementById("StreamStart").value = new Date(startOfHour.getTime() - 1000*60*60).toISOString().substring(0,19);
        document.getElementById("StreamEnd").value = startOfHour.toISOString().substring(0,19);

        loadPlaylist();
    }
};

timestampToBustime = function(ts) {
    date = new Date(ts + "Z");
    return (date < desertBusStart ? "-":"") + videojs.formatTime(Math.abs((date - desertBusStart)/1000), 600.01).padStart(7, "0:");
};

bustimeToTimestamp = function(bustime) {
    direction = 1;
    if(bustime.startsWith("-")) {
        bustime = bustime.slice(1);
        direction = -1;
    }
    parts = bustime.split(':')
    bustime_ms = (parseInt(parts[0]) + parts[1]/60 + parts[2]/3600) * 1000 * 60 * 60;
    return new Date(desertBusStart.getTime() + direction * bustime_ms).toISOString().substring(0, 19);
};

setBustimeRange = function() {
    document.getElementById("BusTimeStart").value = timestampToBustime(document.getElementById("StreamStart").value);
    document.getElementById("BusTimeEnd").value = timestampToBustime(document.getElementById("StreamEnd").value);
};

setStreamRange = function() {
    document.getElementById("StreamStart").value = bustimeToTimestamp(document.getElementById("BusTimeStart").value);
    document.getElementById("StreamEnd").value = bustimeToTimestamp(document.getElementById("BusTimeEnd").value);
}

// For a given select input element id, add the given list of options, defaulting to the first one.
setOptions = function(element, options) {
    options.forEach(function(option, index) {
        document.getElementById(element).innerHTML += '<option value="'+option+'" '+(index==0 ? 'selected':'')+'>'+option+'</option>';
    });
}

loadPlaylist = function(startTrim, endTrim) {
    var playlist = "/playlist/" + document.getElementById("StreamName").value + ".m3u8";

    // If we're using bustime, update stream start/end from it first
    if(document.getElementById("BusTimeToggleBus").checked) {
        setStreamRange();
    }

    var streamStart = document.getElementById("StreamStart").value ? "start="+document.getElementById("StreamStart").value:null;
    var streamEnd = document.getElementById("StreamEnd").value ? "end="+document.getElementById("StreamEnd").value:null;
    var queryString = (streamStart || streamEnd) ? "?" + [streamStart, streamEnd].filter((a) => !!a).join("&"):"";

    setupPlayer(playlist + queryString, startTrim, endTrim);

    //Get quality levels for advanced properties.
    document.getElementById('qualityLevel').innerHTML = "";
    fetch('/files/' + document.getElementById('StreamName').value).then(data => data.json()).then(function (data) {
        if (!data.length) {
            console.log("Could not retrieve quality levels");
            return;
        }
        var qualityLevels = data.sort().reverse();
        setOptions('qualityLevel', qualityLevels);
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
            error = response.statusText + ": " + text;
            console.log(error);
            alert(error);
        } else if (state == 'EDITED') {
            // Only return to dashboard if submitted, not for save draft
            setTimeout(() => { window.location.href = '/thrimbletrimmer/dashboard.html'; }, 500);
            return
        }
        document.getElementById('SubmitButton').disabled = false;
    }));
};

thrimbletrimmerDownload = function() {
    if(player.trimmingControls().options.startTrim >= player.trimmingControls().options.endTrim) {
        alert("End Time must be greater than Start Time");
    } else {
        var discontinuities = mapDiscontinuities();

        var downloadStart = getRealTimeForPlayerTime(discontinuities, player.trimmingControls().options.startTrim);
        var downloadEnd = getRealTimeForPlayerTime(discontinuities, player.trimmingControls().options.endTrim);

        var targetURL = "/cut/" + document.getElementById("StreamName").value +
            "/"+document.getElementById('qualityLevel').options[document.getElementById('qualityLevel').options.selectedIndex].value+".ts" +
            "?start=" + downloadStart +
            "&end=" + downloadEnd +
            "&allow_holes=" + String(document.getElementById('AllowHoles').checked);
        console.log(targetURL);
        document.getElementById('outputFile').src = targetURL;
    }
};

thrimbletrimmerManualLink = function() {
    document.getElementById("ManualButton").disabled = true;
    var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
    body = {link: document.getElementById("ManualLink").value};
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
            error = response.statusText + ": " + text;
            console.log(error);
            alert(error);
            document.getElementById("ManualButton").disabled = false;
        } else {
            alert("Manual link set to " + body.link);
            setTimeout(() => { window.location.href = '/thrimbletrimmer/dashboard.html'; }, 500);
        }
    }));
};

thrimbletrimmerResetLink = function() {
    var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
    if(!confirm(
        'Are you sure you want to reset this event? ' +
        'This will set the row back to UNEDITED and forget about any video that already may exist. ' +
        'It is intended as a last-ditch command to clear a malfunctioning cutter, ' +
        'or if a video needs to be re-edited and replaced. ' +
        'IT IS YOUR RESPONSIBILITY TO DEAL WITH ANY VIDEO THAT MAY HAVE ALREADY BEEN UPLOADED. '
    )) {
        return;
    }
    document.getElementById("ResetButton").disabled = true;
    body = {}
    if (!!user) {
        body.token = user.getAuthResponse().id_token;
    }
    fetch("/thrimshim/reset/"+rowId, {
        method: 'POST',
        headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(body)
    })
    .then(response => response.text().then(text => {
        if (!response.ok) {
            error = response.statusText + ": " + text;
            console.log(error);
            alert(error);
            document.getElementById("ResetButton").disabled = false;
        } else {
            alert("Row has been reset. Reloading...");
            setTimeout(() => { window.location.reload(); }, 500);
        }
    }));
};
