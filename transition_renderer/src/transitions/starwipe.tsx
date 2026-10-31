import React from 'react';
import type {TransitionFrame, TransitionProps} from './types';

export default function starwipe({width, height, progress}: TransitionProps): TransitionFrame {
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.hypot(centerX, centerY) * progress * progress;
  // Ratio of inner to outer points = \phi^2
  const depth_ratio = 2.618;

  // This is just a polygon with 10 points in polar coordinates, evenly spaced angle
  // and alternating distance.
  const points = Array.from({length: 10}, (_: unknown, index: number): string => {
    const angle = -Math.PI / 2 + index * Math.PI / 5;
    const pointRadius = radius * (index % 2 ? 1 : depth_ratio);
    return `${centerX + Math.cos(angle) * pointRadius},${centerY + Math.sin(angle) * pointRadius}`;
  }).join(' ');

  return {
    // Polygon says show the new video inside the lines
    mask: <polygon points={points} />,
    // Decoration says draw a black line on the lines
    decoration: (
      <svg width={width} height={height}>
        <polygon points={points} fill="none" stroke="black"
          strokeWidth={height * 22 / 720} strokeLinejoin="round" />
      </svg>
    ),
  };
}
