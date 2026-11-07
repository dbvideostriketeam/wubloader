import {randomUUID} from 'node:crypto';
import {mkdir, readdir, rename, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {renderMaster, rendererRoot} from './render-master.mjs';

export const resolutions: Record<string, [number, number]> = {
  '480p': [852, 480],
  'source': [1920, 1080],
};

export async function buildMasters(store: string): Promise<void> {
  const version = randomUUID();
  const assets: Record<string, string> = {};
  const effects = (await readdir(path.join(rendererRoot, 'src/transitions')))
    .filter((file: string): boolean => file.endsWith('.tsx')).sort();

  for (const file of effects) {
    const effect = file.slice(0, -4);
    for (const [width, height] of Object.values(resolutions)) {
      const key = `${effect}-${width}-${height}`;
      const relative = path.join('transition-assets', version, `${key}.mkv`);
      const target = path.join(store, relative);

      await renderMaster(effect, width, height, target);
      assets[key] = relative;
    }
  }

  // Write out all generated masters from the container
  const directory = path.join(store, 'transition-assets');
  await mkdir(directory, {recursive: true});
  const temporary = path.join(directory, `.current-${randomUUID()}.json`);
  await writeFile(temporary, JSON.stringify({version, assets}, null, 2) + '\n');
  await rename(temporary, path.join(directory, 'current.json'));
  console.log(`Masters ready: ${version}`);
}
