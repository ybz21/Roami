import { execFileSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';

const files = [...new Set(execFileSync('git', ['ls-files', '-co', '--exclude-standard'], { encoding: 'utf8' }).trim().split('\n'))];
const failures = [];
for (const file of files) {
  if (!existsSync(file)) continue;
  if (!/^(backend|internal|pkg|plugins|cmd|scripts|tests|skills|frontend\/src|\.github)\//.test(file)) continue;
  if (!/\.(go|ts|tsx|sh|yml|yaml|md|tmpl)$/.test(file)) continue;
  const lines = readFileSync(file, 'utf8').split('\n');
  for (const [index, line] of lines.entries()) {
    if (/^\s*(#|\/\/)/.test(line)) continue;
    if (/"(?:ttmux-web\/|ttmux-cli-go\/|roam-plugins\/)/.test(line)) failures.push(`${file}:${index + 1}: obsolete Go import`);
    if (/^(scripts|tests|\.github)\//.test(file) && /(?:cli\/ttmux-cli-go|backend\/go\.(?:mod|sum)|cli\/chrome-cli\/)/.test(line)) failures.push(`${file}:${index + 1}: removed build path`);
    if (/^(scripts|skills|backend\/api\/prompts|plugins\/README)/.test(file) && /(?<![\w/-])ttmux (?:swarm|plugin|capture|send|ls|new|rename|db)\b/.test(line)) failures.push(`${file}:${index + 1}: old CLI call in maintained instructions or scripts`);
    if (/\.(?:go|ts|tsx)$/.test(file) && /ttmux (?:swarm|plugin|capture|send|ls|new|rename|db)\b/.test(line)) failures.push(`${file}:${index + 1}: old command in generated CLI instructions`);
    if (/^(skills|backend\/api\/prompts)\//.test(file) && /(?<![\w/-])ttmux (?=[a-z_])/.test(line)) failures.push(`${file}:${index + 1}: old session command in active agent instructions`);
    if (/^(skills|backend\/api\/prompts)\//.test(file) && /(?<![\w/-])chrome (?:goto|tabs|screenshot|eval|click|fill|record)\b/.test(line) && !/roami chrome /.test(line)) failures.push(`${file}:${index + 1}: old browser command in active agent instructions`);
  }
}
if (failures.length) { process.stderr.write(failures.join('\n') + '\n'); process.exit(1); }
process.stdout.write('CLI entry audit passed\n');
