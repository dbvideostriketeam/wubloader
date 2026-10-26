import starwipe from './starwipe';
import clockwipe from './clockwipe';
import desertbuswipe from './desertbuswipe';
import type {Transition} from './types';

export const transitions: Record<string, Transition> = {starwipe, clockwipe, desertbuswipe};
