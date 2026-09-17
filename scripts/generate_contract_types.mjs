import { existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const repositoryDirectory = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const contractPath = resolve(
  repositoryDirectory,
  process.argv[2] || 'packages/contracts/openapi.yaml',
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
const result = spawnSync(command, [contractPath, '-o', outputPath], {
  cwd: resolve(repositoryDirectory, 'apps/web'),
  stdio: 'inherit',
  shell: process.platform === 'win32',
});

if (result.error) {
  console.error(`[contracts] Unable to execute ${command}: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);
