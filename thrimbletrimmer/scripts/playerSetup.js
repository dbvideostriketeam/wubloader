var player = null;

function setupPlayer(isEditor, source, startTrim, endTrim) {
    document.getElementById("my-player").style.display = "";
    //Make poster of DB logo in correct aspect ratio, to control initial size of fluid container.
    var options = {
        sources: [{ src: source }],
        liveui: true,
        //fluid:true,
        controls:true,
        autoplay:false,
        width:1280,
        height:420,
        playbackRates: [0.5, 1, 1.25, 1.5, 2],
        inactivityTimeout: 0,
        controlBar: {
            fullscreenToggle: true,
            volumePanel: {
                inline: false
            }
        }
    };
    if(player) { //Destroy and recreate the player if it already exists.
        player.dispose(); 
        document.getElementById("EditorContainer").innerHTML = `
            <video id="my-player" class="video-js" controls disablePictureInPicture preload="auto">
                <p class="vjs-no-js">To view this video please enable JavaScript, and consider upgrading to a web browser that <a href="http://videojs.com/html5-video-support/" target="_blank">supports HTML5 video</a></p>
            </video>
        `;
    } 
    player = videojs('my-player', options, function onPlayerReady() {
        videojs.log('Your player is ready!');

        // In this context, `this` is the player that was created by Video.js.
        this.on('ready', function() {
            //this.play();
        });

        this.vhs.playlists.on('loadedmetadata', function() {
            // setTimeout(function() { player.play(); }, 1000);
            player.hasStarted(true); //So it displays all the controls.
            if (isEditor) {
                var stream_start = player.vhs.playlists.master.playlists.filter(playlist => typeof playlist.discontinuityStarts !== "undefined")[0].dateTimeObject;
                startTrim = startTrim ? (new Date(startTrim+"Z")-stream_start)/1000:0;
                endTrim = endTrim ? (new Date(endTrim+"Z")-stream_start)/1000:player.duration();
                var trimmingControls = player.trimmingControls({ startTrim:startTrim, endTrim:endTrim });
            }
        });

        // How about an event listener?
        this.on('ended', function() {
            videojs.log('Awww...over so soon?!');
        });

        this.on('error', function() {
            videojs.log("Could not load video stream");
            alert("No video available for stream.");
        })
    });
    var hlsQS = player.hlsQualitySelector();
}

mapDiscontinuities = function() {
    var playlist = player.vhs.playlists.master.playlists.filter(playlist => typeof playlist.discontinuityStarts !== "undefined")[0]; //Only one of the playlists will have the discontinuity or stream start objects, and it's not necessarily the first one or the source one.
    var discontinuities = playlist.discontinuityStarts.map(segmentIndex => { return {segmentIndex:segmentIndex, segmentTimestamp:playlist.segments[segmentIndex].dateTimeObject, playbackIndex:null}; });
    //var lastDiscontinuity = Math.max(...playlist.discontinuityStarts);
    var lastDiscontinuity = playlist.discontinuityStarts.slice(-1).pop(); //Assumes discontinuities are sorted in ascending order.

    var durationMarker = 0;
    for (var index = 0; index <= lastDiscontinuity; index++) { 
        let segment = playlist.segments[index];
        if(segment.discontinuity) {
            discontinuities.find(discontinuity => discontinuity.segmentIndex == index).playbackIndex = durationMarker;
        }
        durationMarker += segment.duration;
    }

    return discontinuities;
};

getRealTimeForPlayerTime = function(discontinuities, playbackIndex) {
    var streamStart = player.vhs.playlists.master.playlists.filter(playlist => typeof playlist.dateTimeObject !== "undefined")[0].dateTimeObject; //Only one of the playlists will have the discontinuity or stream start objects, and it's not necessarily the first one or the source one.
    
    //Find last discontinuity before playbackIndex
    var lastDiscontinuity = discontinuities.filter(discontinuity => discontinuity.playbackIndex < playbackIndex).slice(-1).pop();
    if(lastDiscontinuity) {
        streamStart = lastDiscontinuity.segmentTimestamp;
        playbackIndex -= lastDiscontinuity.playbackIndex;
    }
    
    return new Date(streamStart.getTime()+playbackIndex*1000).toISOString();
};
