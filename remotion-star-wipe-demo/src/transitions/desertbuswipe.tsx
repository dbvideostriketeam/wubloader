import React from 'react';
import {Img, staticFile} from 'remotion';
import type {TransitionFrame, TransitionProps} from './types';

// Visible bounds of the DB logo from the 2026 media kit
const logoBounds = {left: 2014, top: 266, width: 4039, height: 4040};

export default function desertbuswipe({width, height, progress}: TransitionProps): TransitionFrame {
  const logoScale = height / logoBounds.height;
  const logoHalfWidth = logoBounds.width * logoScale / 2;
  // Gradual start and stop
  const easedProgress = progress * progress * (3 - 2 * progress);
  // Boundary sweeps an area larger than the screen because when the round logo first
  // appears, the left edge is on screen, so the boundary is half a logo right of the
  // right frame edge.
  const boundaryX = width + logoHalfWidth - easedProgress * (width + 2 * logoHalfWidth);

  return {
    mask: <rect x={boundaryX} width={Math.max(0, width - boundaryX)} height={height} />,
    decoration: (
      <Img
        src={staticFile('desert-bus-logo.png')}
        style={{
          position: 'absolute',
          width: 8000 * logoScale,
          height: 4500 * logoScale,
          left: boundaryX - (logoBounds.left + logoBounds.width / 2) * logoScale,
          top: -logoBounds.top * logoScale,
        }}
      />
    ),
  };
}
