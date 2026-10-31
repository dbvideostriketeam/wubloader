import React from 'react';
import type {TransitionFrame, TransitionProps} from './types';

export default function diamondwipe({width, height, progress}: TransitionProps): TransitionFrame {
  const centerX = width / 2;
  const centerY = height / 2;
  const expansion = progress ** 3;
  const horizontalRadius = width * expansion;
  const verticalRadius = height * expansion;
  // This is just a polygon with four points that move from screen center to the center of each edge
  const points = `${centerX},${centerY - verticalRadius} ${centerX + horizontalRadius},${centerY} ` +
    `${centerX},${centerY + verticalRadius} ${centerX - horizontalRadius},${centerY}`;

  return {
    mask: <polygon points={points} />,
    decoration: null,
  };
}
