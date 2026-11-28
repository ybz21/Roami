import assert from 'node:assert/strict'
import { test } from 'node:test'
import { daemonCommand } from './driver.mjs'

const node = '/usr/bin/node'
const driver = '/private fixture/driver.mjs'

test('starts the shared CDP daemon outside the managed pane scope', () => {
  const command = daemonCommand('0::/user.slice/tmux-spawn-pane.scope\n', node, driver)
  assert.deepEqual(command.slice(0, 6), ['systemd-run', '--user', '--scope', '--quiet', '--collect', '--unit'])
  assert.match(command[6], /^roami-chrome-driver-[a-f0-9-]+\.scope$/)
  assert.deepEqual(command.slice(7), ['--', node, driver, '_daemon'])
})

test('preserves normal startup outside managed panes', () => {
  for (const cgroups of ['', '0::/user.slice/roami.service\n', '1:memory:/tmux-spawn-pane.scope\n']) {
    assert.deepEqual(daemonCommand(cgroups, node, driver), [node, driver, '_daemon'])
  }
})
