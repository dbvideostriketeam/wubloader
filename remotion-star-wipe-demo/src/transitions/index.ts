import starwipe from './starwipe';
import clockwipe from './clockwipe';
import type {Transition} from './types';

export const transitions: Record<string, Transition> = {starwipe, clockwipe};
