import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const repositoryDirectory = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const contractPath = resolve(
  repositoryDirectory,
  process.argv[2] || 'packages/contracts/openapi/v0.1/core-api.openapi.json',
);
const outputPath = resolve(
  repositoryDirectory,
  process.argv[3] || 'apps/web/src/generated/api.ts',
);

if (!existsSync(contractPath)) {
  console.error(`[contracts] Missing canonical OpenAPI/JSON Schema: ${contractPath}`);
  console.error('[contracts] Agent A must publish the versioned contract before types can be generated.');
  process.exit(2);
}

mkdirSync(dirname(outputPath), { recursive: true });
const command = process.platform === 'win32' ? 'openapi-typescript.cmd' : 'openapi-typescript';
const temporaryOutputPath = `${outputPath}.generated.tmp`;
const result = spawnSync(command, [contractPath, '-o', temporaryOutputPath], {
  cwd: resolve(repositoryDirectory, 'apps/web'),
  stdio: 'inherit',
  shell: process.platform === 'win32',
});

const cleanupTemporaryOutput = () => {
  if (existsSync(temporaryOutputPath)) unlinkSync(temporaryOutputPath);
};

if (result.error) {
  cleanupTemporaryOutput();
  console.error(`[contracts] Unable to execute ${command}: ${result.error.message}`);
  process.exit(1);
}

if (result.status !== 0) {
  cleanupTemporaryOutput();
  process.exit(result.status ?? 1);
}

try {
  const generated = readFileSync(temporaryOutputPath, 'utf8');
  const source = relative(repositoryDirectory, contractPath).replaceAll('\\', '/');
  const header = [
    '// GENERATED FILE - DO NOT EDIT.',
    `// Source contract: ${source}`,
    '// Contract version: 0.1.0',
    '',
  ].join('\n');
  writeFileSync(outputPath, `${header}${generated}`, 'utf8');
} finally {
  cleanupTemporaryOutput();
}

console.log(`[contracts] Generated ${relative(repositoryDirectory, outputPath).replaceAll('\\', '/')}`);
