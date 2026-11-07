import type {ReactNode} from 'react';

export type TransitionProps = {width: number; height: number; progress: number};
export type TransitionFrame = {mask: ReactNode; decoration: ReactNode};
export type Transition = (props: TransitionProps) => TransitionFrame;
