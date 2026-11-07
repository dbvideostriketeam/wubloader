import {bundle} from '@remotion/bundler';
import {renderFrames, selectComposition} from '@remotion/renderer';
import {mkdir, mkdtemp, rename, rm} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

export const rendererRoot = fileURLToPath(new URL('../../', import.meta.url));

export async function renderMaster(effect: string, width: number, height: number, target: string): Promise<void> {
  await mkdir(path.dirname(target), {recursive: true});
  // Create a temp folder for intermediate files
  const framesDirectory = await mkdtemp(path.join(tmpdir(), 'transition-'));
  const output = path.join(path.dirname(target), `.${path.basename(target)}-${randomUUID()}.tmp.mkv`);

  try {
    // Render the progress samples to PNG with Remotion
    const inputProps = {effect, width, height};
    const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE;
    const serveUrl = await bundle({
      entryPoint: path.join(rendererRoot, 'src/index.tsx'),
      publicDir: path.join(rendererRoot, 'resources'),
    });
    const composition = await selectComposition({serveUrl, id: 'TransitionAsset', inputProps, browserExecutable});
    await renderFrames({
      serveUrl, composition, inputProps, browserExecutable,
      outputDir: framesDirectory,
      imageFormat: 'png',
      concurrency: 2,
      chromiumOptions: {gl: 'swangle'},
      onStart: (): void => console.log(`Rendering ${effect} ${width}x${height}`),
      onFrameUpdate: (): void => {},
    });

    // Assemble the PNGs to a video with ffmpeg
    await new Promise<void>((resolve, reject): void => {
      const ffmpeg = spawn('ffmpeg', [
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

      ffmpeg.on('error', reject);
      ffmpeg.on('close', (code: number | null): void => {
        if (code === 0) {
          resolve();
        } else {
          reject(new Error(`FFmpeg exited ${code}`));
        }
      });
    });

    // Transfer out of the temp folder
    await rename(output, target);
  } finally {
    // Clean up the temp folder/file
    await rm(framesDirectory, {recursive: true, force: true});
    await rm(output, {force: true});
  }
}
