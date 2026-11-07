import path from 'node:path';
import {buildMasters} from './masters.mjs';

await buildMasters(path.resolve(process.argv[2] ?? '/mnt'));
