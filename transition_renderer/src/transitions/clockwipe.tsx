import React from 'react';
import type {TransitionFrame, TransitionProps} from './types';

export default function clockwipe({width, height, progress}: TransitionProps): TransitionFrame {
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.hypot(centerX, centerY);
  const angle = progress * Math.PI * 2 - Math.PI / 2;
  // Coordinates for the end of the clock hand
  const endpointX = centerX + Math.cos(angle) * radius;
  const endpointY = centerY + Math.sin(angle) * radius;
  // Draw a circular segment:
  // M: Start at screen center
  // L: Draw a straight line up, radius long
  // A: Draw a circular arc to endpoint, choosing the larger or smaller direction
  // Z: Draw a straight line back to the beginning
  const wedge = `M ${centerX} ${centerY} L ${centerX} ${centerY - radius} ` +
    `A ${radius} ${radius} 0 ${progress > 0.5 ? 1 : 0} 1 ${endpointX} ${endpointY} Z`;

  return {
    mask: <path d={wedge} />,
    // Also, draw a black line from the origin to the endpoint.
    decoration: (
      <svg width={width} height={height}>
        <line x1={centerX} y1={centerY} x2={endpointX} y2={endpointY} stroke="black"
          strokeWidth={height * 20 / 720} strokeLinecap="round" />
      </svg>
    ),
  };
}
