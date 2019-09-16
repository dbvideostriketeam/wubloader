/*! @name videojs-trimming-controls @version 0.0.0 @license MIT */
import videojs from 'video.js';

function _inheritsLoose(subClass, superClass) {
  subClass.prototype = Object.create(superClass.prototype);
  subClass.prototype.constructor = subClass;
  subClass.__proto__ = superClass;
}

var version = "0.0.0";

var Plugin = videojs.getPlugin('plugin'); // Default options for the plugin.

var defaults = {
  startTrim: 60,
  endTrim: 120,
  limitPlayback: false
};
/**
 * An advanced Video.js plugin. For more information on the API
 *
 * See: https://blog.videojs.com/feature-spotlight-advanced-plugins/
 */

var TrimmingControls =
/*#__PURE__*/
function (_Plugin) {
  _inheritsLoose(TrimmingControls, _Plugin);

  /**
   * Create a TrimmingControls plugin instance.
   *
   * @param  {Player} player
   *         A Video.js Player instance.
   *
   * @param  {Object} [options]
   *         An optional options object.
   *
   *         While not a core part of the Video.js plugin architecture, a
   *         second argument of options is a convenient way to accept inputs
   *         from your plugin's caller.
   */
  function TrimmingControls(player, options) {
    var _this;

    // the parent class will add player under this.player
    _this = _Plugin.call(this, player) || this;
    _this.options = videojs.mergeOptions(defaults, options);

    _this.createTrimmingControls();

    player.ready(function () {
      setTimeout(function () {
        _this.updateTrimTimes(_this.options.startTrim, _this.options.endTrim);
      }, 100);
      player.on("timeupdate", function () {
        if (_this.options.limitPlayback && _this.player.currentTime() >= _this.options.endTrim) {
          _this.player.currentTime(_this.options.endTrim);

          _this.player.pause();
        }
      });
      player.on('playing', function () {
        videojs.log('playback began!');

        _this.updateTrimTimes(_this.options.startTrim, _this.options.endTrim);
      });
    });
    return _this;
  }

  var _proto = TrimmingControls.prototype;

  _proto.createTrimmingControls = function createTrimmingControls() {
    var player = this.player;
    var videoJsComponentClass = videojs.getComponent('Component');
    /**
     * Extend vjs button class for quality button.
     */

    var TrimControlBarClass =
    /*#__PURE__*/
    function (_videoJsComponentClas) {
      _inheritsLoose(TrimControlBarClass, _videoJsComponentClas);

      /**
       * Component constructor.
       */
      function TrimControlBarClass() {
        return _videoJsComponentClas.call(this, player, {
          title: player.localize('Trimming Controls')
        }) || this;
      }

      var _proto2 = TrimControlBarClass.prototype;

      _proto2.createEl = function createEl() {
        return videojs.dom.createEl('div', {
          // Prefixing classes of elements within a player with "vjs-" is a convention used in Video.js.
          className: 'vjs-control-bar vjs-trimming-controls',
          dir: 'ltr'
        });
      };

      return TrimControlBarClass;
    }(videoJsComponentClass);

    var videoJSSpacerClass = videojs.getComponent('Spacer');
    var videoJSButtonClass = videojs.getComponent('Button');

    var GoToButtonClass =
    /*#__PURE__*/
    function (_videoJSButtonClass) {
      _inheritsLoose(GoToButtonClass, _videoJSButtonClass);

      function GoToButtonClass(_plugin, _targetPosition, _text) {
        var _this2;

        _this2 = _videoJSButtonClass.call(this, player, {// title: player.localize('Trim Button'), 
          // label: "Trim Here"
        }) || this;
        _this2.trimmingControls = _plugin;
        _this2.targetPosition = _targetPosition;

        _this2.controlText(_text);

        _this2.el().getElementsByClassName('vjs-icon-placeholder')[0].classList += " material-icons";
        return _this2;
      }

      var _proto3 = GoToButtonClass.prototype;

      _proto3.handleClick = function handleClick() {
        if (this.targetPosition == 0) {
          this.player().currentTime(this.trimmingControls.options.startTrim);
        } else if (this.targetPosition == 1) {
          this.player().currentTime(this.trimmingControls.options.endTrim);
        }
      };

      return GoToButtonClass;
    }(videoJSButtonClass);

    var TrimButtonClass =
    /*#__PURE__*/
    function (_videoJSButtonClass2) {
      _inheritsLoose(TrimButtonClass, _videoJSButtonClass2);

      function TrimButtonClass(_plugin, _targetPosition, _text) {
        var _this3;

        _this3 = _videoJSButtonClass2.call(this, player, {// title: player.localize('Trim Button'), 
          // label: "Trim Here"
        }) || this;
        _this3.trimmingControls = _plugin;
        _this3.targetPosition = _targetPosition;

        _this3.controlText(_text);

        _this3.el().getElementsByClassName('vjs-icon-placeholder')[0].classList += " material-icons";
        return _this3;
      }

      var _proto4 = TrimButtonClass.prototype;

      _proto4.handleClick = function handleClick() {
        if (this.targetPosition == 0) {
          this.trimmingControls.updateTrimTimes(this.player().currentTime(), this.trimmingControls.options.endTrim);
        } else if (this.targetPosition == 1) {
          this.trimmingControls.updateTrimTimes(this.trimmingControls.options.startTrim, this.player().currentTime());
        }
      };

      return TrimButtonClass;
    }(videoJSButtonClass);

    var TrimTimeDisplayClass =
    /*#__PURE__*/
    function (_videoJsComponentClas2) {
      _inheritsLoose(TrimTimeDisplayClass, _videoJsComponentClas2);

      function TrimTimeDisplayClass(_defaultTime) {
        var _this4;

        _this4 = _videoJsComponentClas2.call(this, player, {}) || this;

        _this4.updateTimeContent(_defaultTime);

        return _this4;
      }

      var _proto5 = TrimTimeDisplayClass.prototype;

      _proto5.createEl = function createEl() {
        return videojs.dom.createEl('input', {
          // Prefixing classes of elements within a player with "vjs-" is a convention used in Video.js.
          className: 'vjs-time-display'
        });
      };

      _proto5.updateTimeContent = function updateTimeContent(timeInSeconds) {
        videojs.dom.emptyEl(this.el()); //this.controlText(videojs.formatTime(timeInSeconds, 600))
        //videojs.dom.appendContent(this.el(), videojs.formatTime(timeInSeconds, 600));
        //videojs.dom.textContent(this.el(), videojs.formatTime(timeInSeconds, 600));

        this.el().value = videojs.formatTime(timeInSeconds, 600.01);
      };

      return TrimTimeDisplayClass;
    }(videoJsComponentClass);

    var FrameButtonClass =
    /*#__PURE__*/
    function (_videoJSButtonClass3) {
      _inheritsLoose(FrameButtonClass, _videoJSButtonClass3);

      function FrameButtonClass(_plugin, _targetPosition, _text) {
        var _this5;

        _this5 = _videoJSButtonClass3.call(this, player, {// title: player.localize('Trim Button'), 
          // label: "Trim Here"
        }) || this;
        _this5.trimmingControls = _plugin;
        _this5.targetPosition = _targetPosition;

        _this5.controlText(_text);

        _this5.el().getElementsByClassName('vjs-icon-placeholder')[0].classList += " material-icons";
        return _this5;
      }

      var _proto6 = FrameButtonClass.prototype;

      _proto6.handleClick = function handleClick() {
        if (this.targetPosition == 0) {
          this.player().currentTime(this.player().currentTime() - 0.1);
        } else if (this.targetPosition == 1) {
          this.player().currentTime(this.player().currentTime() + 0.1);
        }
      };

      return FrameButtonClass;
    }(videoJSButtonClass);

    var videoJSPlayToggleClass = videojs.getComponent('PlayToggle');

    var playbackEndToggleClass =
    /*#__PURE__*/
    function (_videoJSButtonClass4) {
      _inheritsLoose(playbackEndToggleClass, _videoJSButtonClass4);

      function playbackEndToggleClass(_plugin, _text) {
        var _this6;

        _this6 = _videoJSButtonClass4.call(this, player, {// title: player.localize('Trim Button'), 
          // label: "Trim Here"
        }) || this;
        _this6.trimmingControls = _plugin;

        _this6.controlText(_text);

        _this6.el().getElementsByClassName('vjs-icon-placeholder')[0].classList += " material-icons";
        return _this6;
      }

      var _proto7 = playbackEndToggleClass.prototype;

      _proto7.handleClick = function handleClick() {
        this.trimmingControls.options.limitPlayback = !this.trimmingControls.options.limitPlayback;
        this.toggleClass('playbackLimited');
      };

      return playbackEndToggleClass;
    }(videoJSButtonClass); //Creating Trimming Seek Bar


    this._trimSeekControlBar = new TrimControlBarClass();
    var trimSeekControlBarInstance = player.addChild(this._trimSeekControlBar, {
      componentClass: 'trimControlBar'
    }, player.children().length);
    trimSeekControlBarInstance.addClass('vljs-trim-seek');
    trimSeekControlBarInstance.el().innerHTML = '<div id="trimBarPlaceholderContainer"><div id="trimBarPlaceholder"></div></div>'; // //Spacer
    // this._spacer1 = new videoJSSpacerClass();
    // const spacer1Instance = this._trimSeekControlBar.addChild(this._spacer1, {componentClass: 'spacer'}, 0);
    // spacer1Instance.setAttribute("style", "flex: 0 0 158px");
    // //Spacer
    // this._spacer1 = new videoJSSpacerClass();
    // const spacer2Instance = this._trimSeekControlBar.addChild(this._spacer1, {componentClass: 'spacer'}, 2);
    // spacer2Instance.setAttribute("style", "flex: 0 0 178px");
    //Creating Trimming Controls Bar

    this._trimControlBar = new TrimControlBarClass();
    var trimControlBarInstance = player.addChild(this._trimControlBar, {
      componentClass: 'trimControlBar'
    }, player.children().length);
    trimControlBarInstance.addClass('vljs-trim-buttons'); //Trim Bar Controls order: spacer,GoTo,Time,SetPlayhead,frameadjust,playpause,frameAdjust,setPlayhead,time,GoTo, endplayback
    //Spacer for balance

    this._spacer = new videoJSSpacerClass();

    var spacerInstance = this._trimControlBar.addChild(this._spacer, {
      componentClass: 'spacer'
    }, 0); //Go To start of Trim


    this._startGoToButton = new GoToButtonClass(this, 0, "Go to start of trim segment");

    var startGoToButtonInstance = this._trimControlBar.addChild(this._startGoToButton, {
      componentClass: 'goToButton'
    }, 5);

    startGoToButtonInstance.addClass('vljs-trimming-button');
    startGoToButtonInstance.el().getElementsByClassName('vjs-icon-placeholder')[0].innerText = "skip_previous"; //Create trim start time display

    this._startTrimTimeDisplay = new TrimTimeDisplayClass(this.options.startTrim);

    var startTrimTimeDisplayInstance = this._trimControlBar.addChild(this._startTrimTimeDisplay, {
      componentClass: 'trimTimeDisplay'
    }, 10);

    startTrimTimeDisplayInstance.on("change", function () {
      this.player_.trimmingControls().setTimestamps(startTrimTimeDisplayInstance.el().value, 0);
    }); //Create set start at playhead button

    this._startTrimButton = new TrimButtonClass(this, 0, "Set trim start at playhead");

    var startTrimButtonInstance = this._trimControlBar.addChild(this._startTrimButton, {
      componentClass: 'trimButton'
    }, 20);

    startTrimButtonInstance.addClass('vljs-trimming-button');
    startTrimButtonInstance.el().getElementsByClassName('vjs-icon-placeholder')[0].innerText = "edit"; //Create Frame Back Button

    this._frameBackButton = new FrameButtonClass(this, 0, "Move back 1 frame");

    var frameBackButtonInstance = this._trimControlBar.addChild(this._frameBackButton, {
      componentClass: 'frameButton'
    }, 22);

    frameBackButtonInstance.addClass('vljs-trimming-button');
    frameBackButtonInstance.el().getElementsByClassName('vjs-icon-placeholder')[0].innerText = "fast_rewind"; //Create Play/Pause Button

    this._playPauseButton = new videoJSPlayToggleClass(this.player);

    var playPauseButtonInstance = this._trimControlBar.addChild(this._playPauseButton, {
      componentClass: 'playPauseButton'
    }, 25); //Create Frame Forward Button


    this._frameForwardButton = new FrameButtonClass(this, 1, "Move forward 1 frame");

    var frameForwardButtonInstance = this._trimControlBar.addChild(this._frameForwardButton, {
      componentClass: 'frameButton'
    }, 27);

    frameForwardButtonInstance.addClass('vljs-trimming-button');
    frameForwardButtonInstance.el().getElementsByClassName('vjs-icon-placeholder')[0].innerText = "fast_forward"; //Create set end at playhead button

    this._endTrimButton = new TrimButtonClass(this, 1, "Set trim end at playhead");

    var endTrimButtonInstance = this._trimControlBar.addChild(this._endTrimButton, {
      componentClass: 'trimButton'
    }, 30);

    endTrimButtonInstance.addClass('vljs-trimming-button');
    endTrimButtonInstance.el().getElementsByClassName('vjs-icon-placeholder')[0].innerText = "edit"; //Create trim end time display

    this._endTrimTimeDisplay = new TrimTimeDisplayClass(this.options.endTrim);

    var endTrimTimeDisplayInstance = this._trimControlBar.addChild(this._endTrimTimeDisplay, {
      componentClass: 'trimTimeDisplay'
    }, 40);

    endTrimTimeDisplayInstance.on("change", function () {
      this.player_.trimmingControls().setTimestamps(endTrimTimeDisplayInstance.el().value, 1);
    }); //Go To end of Trim

    this._endGoToButton = new GoToButtonClass(this, 1, "Go to end of trim segment");

    var endGoToButtonInstance = this._trimControlBar.addChild(this._endGoToButton, {
      componentClass: 'goToButton'
    }, 50);

    endGoToButtonInstance.addClass('vljs-trimming-button');
    endGoToButtonInstance.el().getElementsByClassName('vjs-icon-placeholder')[0].innerText = "skip_next"; //End playback at trim endpoint

    this._playbackEndToggle = new playbackEndToggleClass(this, "End playback at trim endpoint");

    var playbackEndToggleInstance = this._trimControlBar.addChild(this._playbackEndToggle, {
      componentClass: 'playbackEndToggle'
    }, 60);

    playbackEndToggleInstance.addClass('vljs-trimming-button');
    playbackEndToggleInstance.el().getElementsByClassName('vjs-icon-placeholder')[0].innerText = "stop";
  };

  _proto.updateTrimTimes = function updateTrimTimes(startValue, endValue) {
    //Update stored values
    this.options.startTrim = startValue;
    this.options.endTrim = endValue; //Update timestamp displays

    this._startTrimTimeDisplay.updateTimeContent(startValue);

    this._endTrimTimeDisplay.updateTimeContent(endValue); //Update slider


    document.getElementById("trimBarPlaceholder").style["marginLeft"] = startValue / this.player.duration() * 100 + "%";
    document.getElementById("trimBarPlaceholder").style["marginRight"] = 100 - endValue / this.player.duration() * 100 + "%";
  };

  _proto.setTimestamps = function setTimestamps(value, index) {
    if (/^\d*:?\d*:?\d*\.?\d*$/.test(value)) {
      if (index === 0) {
        this.updateTrimTimes(this.getSeconds(value), this.options.endTrim);
      } else if (index === 1) {
        this.updateTrimTimes(this.options.startTrim, this.getSeconds(value));
      }
    } else {
      this._startTrimTimeDisplay.updateTimeContent(startValue);

      this._endTrimTimeDisplay.updateTimeContent(endValue);
    }
  };

  _proto.getSeconds = function getSeconds(time) {
    var timeArr = time.split(':'),
        //Array of hours, minutes, and seconds.
    s = 0,
        //Seconds total
    m = 1; //Multiplier

    while (timeArr.length > 0) {
      //Iterate through time segments starting from the seconds,
      s += m * timeArr.pop(); //multiply as  appropriate, and add to seconds total,

      m *= 60; //increase multiplier.
    }

    return s;
  };

  return TrimmingControls;
}(Plugin); // Define default values for the plugin's `state` object here.


TrimmingControls.defaultState = {}; // Include the version number.

TrimmingControls.VERSION = version; // Register the plugin with video.js.

videojs.registerPlugin('trimmingControls', TrimmingControls);

export default TrimmingControls;
