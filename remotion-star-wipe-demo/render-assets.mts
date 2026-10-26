import {bundle} from '@remotion/bundler';
import {renderFrames, selectComposition} from '@remotion/renderer';
import {mkdir, mkdtemp, rename, rm} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

async function main(): Promise<void> {
  if (process.argv.length !== 6) {
    throw new Error('Usage: npm run render:assets -- EFFECT WIDTH HEIGHT CACHE_DIR');
  }

  // Parse arguments
  const [effect, widthArgument, heightArgument, cacheArgument] = process.argv.slice(2);
  const width = Number(widthArgument);
  const height = Number(heightArgument);
  const cacheDirectory = path.resolve(cacheArgument);
  const rendererRoot = fileURLToPath(new URL('../../', import.meta.url));

  // Create a temp folder for intermediate files
  await mkdir(cacheDirectory, {recursive: true});
  const framesDirectory = await mkdtemp(path.join(cacheDirectory, '.render-'));

  try {
    // Render the progress samples to PNG with Remotion
    const inputProps = {effect, width, height};
    const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE;
    const serveUrl = await bundle({
      entryPoint: path.join(rendererRoot, 'src/index.tsx'),
    });
    const composition = await selectComposition({serveUrl, id: 'TransitionAsset', inputProps, browserExecutable});
    await renderFrames({
      serveUrl, composition, inputProps, browserExecutable,
      outputDir: framesDirectory,
      imageFormat: 'png',
      concurrency: 2,
      chromiumOptions: {gl: 'swangle'},
      onStart: (): void => console.log('Rendering progress samples'),
      onFrameUpdate: (): void => {},
    });

    // Assemble the PNGs to a video with ffmpeg
    const output = path.join(framesDirectory, 'asset.mkv');
    const result = spawnSync('ffmpeg', [
      '-hide_banner', '-loglevel', 'error', '-y',
      '-framerate', String(composition.fps),
      '-pattern_type', 'glob', '-i', path.join(framesDirectory, 'element-*.png'),
      '-filter_complex', '[0:v]split[mask][decoration];' +
        `[mask]crop=${width}:${height}:0:0,format=gray[maskout];` +
        `[decoration]crop=${width}:${height}:${width}:0,format=bgra[decorationout]`,
      '-map', '[maskout]', '-map', '[decorationout]', '-c:v', 'ffv1',
      '-metadata:s:v:0', 'title=Reveal mask',
      '-metadata:s:v:1', 'title=Decoration',
      output,
    ], {stdio: 'inherit'});

    if (result.error) {
      throw result.error;
    }
    if (result.status !== 0) {
      throw new Error(`FFmpeg exited ${result.status}`);
    }

    // Transfer out of the temp folder
    const target = path.join(cacheDirectory, `${effect}-${width}-${height}.mkv`);
    await rename(output, target);
    console.log(target);
  } finally {
    // Clean up the temp folder
    await rm(framesDirectory, {recursive: true, force: true});
  }
}

await main();
