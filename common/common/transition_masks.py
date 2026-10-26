"""Alternate transitions using mask MKV videos, typically pre-rendered with Remotion."""
import math
import os
from fractions import Fraction


MASK_TRANSITIONS: dict[str, str] = {
    'starwipe': 'An expanding outlined star.',
    'clockwipe': 'A clockwise sweep with a black progression line.',
}
ASSET_INTERVALS = 300


def asset_path(effect: str, width: int, height: int) -> str:
    """Assemble the filename for the transition master assets."""
    return os.path.join(os.environ['WUBLOADER_TRANSITION_ASSETS'], f'{effect}-{width}-{height}.mkv')


def mask_filters(
    previous: str, incoming: str, asset: str, output: str,
    offset: float, duration: float, fps: str, prefix: str,
) -> list[str]:
    """Apply the transition mask filter to a provided set of video sources.

    Inputs:
    - previous: outgoing video stream selector, usually 0:v
    - incoming: incoming video stream selector, usually 1:v
    - asset: video stream selector for the mask filter master, usually 2:v
    - output: video stream selector for the output
    - offset: transition start time, offset relative to the beginning of previous
    - duration: transition duration
    - fps: desired output frame rate
    - prefix: unique prefix for this filter, for when this is called multiple times for the same ffmpeg call
    """

    frame_rate = float(Fraction(fps))
    frame_count = round(duration * frame_rate)
    transition_end = math.ceil(round((offset + duration) * frame_rate, 6))
    transition_start = transition_end - frame_count

    # Retime the transition mask filter to the current fps and duration
    retime = (
        f'settb=AVTB,setpts=N*{frame_count - 1}/({fps})/{ASSET_INTERVALS}/TB,'
        f'tpad=stop_mode=clone:stop_duration=1,fps={fps}:start_time=0:round=up,'
        f'trim=end_frame={frame_count}'
    )

    filters = [
        # Split sources - prein (unaffected by transition), oldin/newin (transition), postin (unaffected)
        f'[{previous}]settb=AVTB,setpts=PTS-STARTPTS,fps={fps},split=2[{prefix}prein][{prefix}oldin]',
        f'[{incoming}]settb=AVTB,setpts=PTS-STARTPTS,fps={fps},split=2[{prefix}newin][{prefix}postin]',

        # Trim oldin, newin, postin to old, new, post
        f'[{prefix}oldin]trim=start_frame={transition_start}:end_frame={transition_end},'
        f'setpts=PTS-STARTPTS,format=yuv444p,setsar=1[{prefix}old]',
        f'[{prefix}newin]trim=end_frame={frame_count},setpts=PTS-STARTPTS,format=yuv444p,setsar=1[{prefix}new]',
        f'[{prefix}postin]trim=start_frame={frame_count},setpts=PTS-STARTPTS,setsar=1[{prefix}post]',

        # Retime and split the mask part of the transition asset to y/u/v
        f'[{asset}:0]{retime},split=3[{prefix}mask_y][{prefix}mask_u][{prefix}mask_v]',
        f'[{prefix}mask_y][{prefix}mask_u][{prefix}mask_v]mergeplanes=0x001020:format=yuv444p[{prefix}matte]',
        # Retime and format the overlay part of the transition asset
        f'[{asset}:1]{retime},format=rgba[{prefix}decoration]',

        # Apply the masking part of the transition asset as a maskedmerge
        f'[{prefix}old][{prefix}new][{prefix}matte]maskedmerge[{prefix}merged]',
        # And the overlay part of the transition asset as an overlay
        f'[{prefix}merged][{prefix}decoration]overlay=eof_action=repeat:format=yuv444:alpha=straight,'
        f'trim=end_frame={frame_count},setsar=1[{prefix}transition]',
    ]

    if transition_start > 0:
        # Trim prein and concat
        filters += [
            f'[{prefix}prein]trim=end_frame={transition_start},setpts=PTS-STARTPTS,setsar=1[{prefix}pre]',
            f'[{prefix}pre][{prefix}transition][{prefix}post]concat=n=3:v=1:a=0,fps={fps},settb=AVTB[{output}]',
        ]
    else:
        # Nullsink prein and concat
        filters += [
            f'[{prefix}prein]nullsink',
            f'[{prefix}transition][{prefix}post]concat=n=2:v=1:a=0,fps={fps},settb=AVTB[{output}]',
        ]

    return filters
