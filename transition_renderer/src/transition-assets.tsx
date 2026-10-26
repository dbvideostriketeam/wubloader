import React from 'react';
import {AbsoluteFill, Composition, useCurrentFrame} from 'remotion';
import {transitions} from './transitions';

export type Props = {effect: string; width: number; height: number};
// INTERVALS is the number of gaps between frames - so we generate this
// many plus one frames. Each frame advances the `progress` slider by
// the reciprocal of this.
export const INTERVALS = 300;

// Framing to build the PNG assets. Side by side we render two things. The left is
// the grayscale fade between the two video sources. The right is any RGBA overlay.
const TransitionAsset = ({effect, width, height}: Props): React.JSX.Element => {
  const progress = useCurrentFrame() / INTERVALS;
  const {mask, decoration} = transitions[effect]({width, height, progress});

  return (
    <AbsoluteFill>
      <svg width={width} height={height} style={{position: 'absolute', left: 0}}>
        <rect width={width} height={height} fill="black" />
        {progress >= 1 ? <rect width={width} height={height} fill="white" />
          : progress > 0 ? <g fill="white">{mask}</g> : null}
      </svg>
      <div style={{position: 'absolute', left: width, width, height, overflow: 'hidden'}}>
        {progress > 0 && progress < 1 ? decoration : null}
      </div>
    </AbsoluteFill>
  );
};

export const AssetComposition = (): React.JSX.Element => (
  <Composition
    id="TransitionAsset"
    component={TransitionAsset}
    width={1704}
    height={480}
    fps={INTERVALS}
    durationInFrames={INTERVALS + 1}
    defaultProps={{effect: 'starwipe', width: 852, height: 480}}
    calculateMetadata={({props}: {props: Props}): {width: number; height: number} =>
      ({width: props.width * 2, height: props.height})}
  />
);
