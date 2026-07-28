#!/usr/bin/env node
/**
 * Wrapper script for the `import_thinkhazard` Python command.
 *
 * Resolves the local `--input` file path, mounts it into the Docker container,
 * and delegates to the `import_thinkhazard` console script.
 *
 * Usage:
 *   npm run import:thinkhazard -- --input /path/to/export.csv [options]
 *
 * Options are forwarded verbatim to the underlying Python command.
 */

'use strict';

const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const args = process.argv.slice(2);
const inputIndex = args.indexOf('--input');

if (inputIndex === -1 || inputIndex >= args.length - 1) {
  console.error('Error: --input <path> is required.');
  console.error('Usage: npm run import:thinkhazard -- --input <path_to_csv> [options]');
  process.exit(1);
}

const inputPath = args[inputIndex + 1];
const absoluteInput = path.resolve(inputPath);

if (!fs.existsSync(absoluteInput)) {
  console.error(`Error: input file not found: ${absoluteInput}`);
  process.exit(1);
}

const filename = path.basename(absoluteInput);
const containerPath = `/tmp/${filename}`;

// Build the docker compose command, mounting the input file read-only.
const dockerArgs = [
  'compose', 'run', '--rm',
  '-v', `${absoluteInput}:${containerPath}:ro`,
  'thinkhazard',
  'import_thinkhazard',
  '--input', containerPath,
];

// Forward any extra arguments (e.g. --verbose, --dry-run) to the Python command.
const extraArgs = args.filter((_, i) => i !== inputIndex && i !== inputIndex + 1);
dockerArgs.push(...extraArgs);

const result = spawnSync('docker', dockerArgs, { stdio: 'inherit' });
process.exit(result.status !== null ? result.status : 1);
