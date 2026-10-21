# Managed browser tasks

Native bash accepts these actual `roami chrome` command forms, with argv as an array:

```bash
roami chrome help
roami chrome new https://example.com
roami chrome observe --resource RESOURCE_ID
roami chrome goto https://example.com/source --observation OBSERVATION_ID
roami chrome screenshot --resource RESOURCE_ID
roami chrome click 'button[type=submit]' --observation OBSERVATION_ID
roami chrome fill 'input[name=q]' 'query' --observation OBSERVATION_ID
roami chrome type textarea 'text' --observation OBSERVATION_ID
roami chrome press Enter --observation OBSERVATION_ID
```

Resource and observation IDs come from the latest returned observation, not from guessed tab positions. `--resource` and `--observation` use the host's admitted task context; the terminal CLI also supports them inside an active Agent tool call. The host records the underlying operation, effect and durable receipt. Native tasks cannot substitute arbitrary `--cdp`, eval, shell wrappers or receipt directories.

Research allows new, observe, screenshot and goto only. It cannot claim an existing user tab with `observe --target TARGET_ID`, interact with forms, or use standalone Shell. Ordinary Workers can claim existing targets only when node policy allows it.

If new returns resourceId with an observation error, observe that resource; do not create another tab. On CHROME_SCENE_CHANGED, observe again and use the fresh observation ID. On navigation failure, observe the same resource and choose an accessible source within the original request. Unknown writes and human takeover stop input.

If that unchanged resource returns BROWSER_SOURCE_UNAVAILABLE, stop observing it. Once read-only input is proved stopped, choose another relevant provider when the user did not require this one. Do not chase many entrances to an optional unavailable provider. A zero tab budget means unlimited; a positive budget is explicit. If finalizeFromEvidence=true, use no more tools: report this attempt's verified findings and limitations.

Observations already contain persisted PNG artifactRefs. For requested screenshots return the exact downloadUrl after checking page identity; ordinary research returns source links. No extra workspace or file copy is needed. Professional terminal files use `/api/file/raw?path=` plus the URL-encoded absolute path; HTML with relative assets uses `/api/file/serve/`.
