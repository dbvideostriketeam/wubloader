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
            //data = testThrimShim;
            desertBusStart = new Date(data.bustime_start);
            document.getElementById("hiddenSubmissionID").value = data.id;
            document.getElementById("StreamName").value = data.video_channel ? data.video_channel:document.getElementById("StreamName").value;
            document.getElementById("StreamStart").value = data.event_start;
            document.getElementById("BusTimeStart").value = (new Date(data.event_start+"Z") < desertBusStart ? "-":"") + videojs.formatTime(Math.abs((new Date(data.event_start+"Z") - desertBusStart)/1000), 600.01).padStart(7, "0:");
            document.getElementById("StreamEnd").value = data.event_end;
            document.getElementById("BusTimeEnd").value = (new Date(data.event_end+"Z") < desertBusStart ? "-":"") + videojs.formatTime(Math.abs((new Date(data.event_end+"Z") - desertBusStart)/1000), 600.01).padStart(7, "0:");
            document.getElementById("VideoTitle").value = data.video_title ? data.video_title:document.getElementById("VideoTitle").value;
            document.getElementById("VideoDescription").value = data.video_description ? data.video_description:data.description;

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

loadPlaylist = function(startTrim, endTrim) {
    var playlist = "/playlist/" + document.getElementById("StreamName").value + ".m3u8";

    if(document.getElementById("BusTimeToggleBus").checked) {
        var streamStart = desertBusStart;
        var busTimeStart = document.getElementById("BusTimeStart").value;
        var busTimeEnd = document.getElementById("BusTimeEnd").value;
        
        //Convert BusTime to milliseconds from start of stream
        busTimeStart = (parseInt(busTimeStart.split(':')[0]) + busTimeStart.split(':')[1]/60)  * 1000 * 60 * 60;
        busTimeEnd = (parseInt(busTimeEnd.split(':')[0]) + busTimeEnd.split(':')[1]/60)  * 1000 * 60 * 60;
        
        document.getElementById("StreamStart").value = new Date(streamStart.getTime() + busTimeStart).toISOString().substring(0,19);
        document.getElementById("StreamEnd").value = new Date(streamStart.getTime() + busTimeEnd).toISOString().substring(0,19);
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
        qualityLevels.forEach(function(level, index) {
            document.getElementById('qualityLevel').innerHTML += '<option value="'+level+'" '+(index==0 ? 'selected':'')+'>'+level+'</option>';
        });
    });
};

thrimbletrimmerSubmit = function(state) {
    document.getElementById('SubmitButton').disabled = true;
    if(player.trimmingControls().options.startTrim >= player.trimmingControls().options.endTrim) {
        alert("End Time must be greater than Start Time");
        document.getElementById('SubmitButton').disabled = false;
    } else {
        var discontinuities = mapDiscontinuities();

        var wubData = {
            video_start:getRealTimeForPlayerTime(discontinuities, player.trimmingControls().options.startTrim).replace('Z',''),
            video_end:getRealTimeForPlayerTime(discontinuities, player.trimmingControls().options.endTrim).replace('Z',''),
            video_title:document.getElementById("VideoTitle").value,
            video_description:document.getElementById("VideoDescription").value,
            allow_holes:String(document.getElementById('AllowHoles').checked),
            upload_location:document.getElementById('uploadLocation').value,
            video_channel:document.getElementById("StreamName").value,
            video_quality:document.getElementById('qualityLevel').options[document.getElementById('qualityLevel').options.selectedIndex].value,
            uploader_whitelist:(document.getElementById('uploaderWhitelist').value ? document.getElementById('uploaderWhitelist').value.split(','):null),
            state:state,
            token: user.getAuthResponse().id_token
        };
        // state_columns = ['state', 'uploader', 'error', 'video_link'] 
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
        .then(response => { if (!response.ok) { throw Error(response.statusText); }; return response; })
        .then(data => { console.log(data); setTimeout(() => { window.location.href = '/thrimbletrimmer/dashboard.html'; }, 500); })
        .catch(error => { console.log(error); alert(error); });
    }
};

thrimbletrimmerDownload = function() {
    document.getElementById('SubmitButton').disabled = true;
    if(player.trimmingControls().options.startTrim >= player.trimmingControls().options.endTrim) {
        alert("End Time must be greater than Start Time");
        document.getElementById('SubmitButton').disabled = false;
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
    var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
    fetch("/thrimshim/manual-link/"+rowId, {
        method: 'POST',
        headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            link: document.getElementById("ManualLink").value, 
            token: user.getAuthResponse().id_token
        })
    })
    .then(response => { if (!response.ok) { throw Error(response.statusText); }; return response; })
    .then(data => { console.log(data); setTimeout(() => { alert("Manual link set"); }, 500); })
    .catch(error => { console.log(error); alert(error); });
};

thrimbletrimmerResetLink = function() {
    var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
    if(confirm('Are you sure you want to reset this event?')) {
        fetch("/thrimshim/reset/"+rowId, {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({token: user.getAuthResponse().id_token})
        })
        .then(response => { if (!response.ok) { throw Error(response.statusText); }; return response; })
        .then(data => { console.log(data); setTimeout(() => { window.location.reload() }, 500); })
        .catch(error => { console.log(error); alert(error); });
    }
};
