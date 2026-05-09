# Recording Shot List

## Shot 1 -- Landing Hero

Show:

- `Install AI workers into the AI you already use.`
- `Start with Auth Bug Core`

Say:

Cambrian lets you install AI worker packs into the AI you already use.

Hide:

- Browser bookmarks
- personal folders
- unrelated tabs

Expected output:

- The viewer understands Cambrian as an AI Worker Installer.

## Shot 2 -- Auth Bug Core Pack Page

Show:

- Best for Python + pytest + auth/login bug fixes
- Included workers, team, template
- Install command

Say:

Auth Bug Core is the first worker pack. It is intentionally narrow.

Hide:

- raw local paths
- advanced lifecycle links

Expected output:

- Auth Bug Core is understood as the launch pack.

## Shot 3 -- Terminal: pack show

Command:

```bash
cambrian pack show auth-bug-core
```

Say:

This shows what the worker pack is for and how to install it.

Hide:

- private terminal prompt paths

Expected output:

- pack id: `auth-bug-core`
- install command
- lane fit

## Shot 4 -- Terminal: install

Command:

```bash
cambrian install pack auth-bug-core
```

Say:

Install writes local Cambrian state. It does not modify source code.

Hide:

- full absolute user paths

Expected output:

- installed workers
- installed team/template/workset

## Shot 5 -- Terminal: activate

Command:

```bash
cambrian pack activate auth-bug-core
```

Say:

Activation selects this pack as the current work context.

Hide:

- unrelated `.cambrian` internals

Expected output:

- active pack
- recommended first job: `cambrian pack start "로그인 에러 수정해"`

## Shot 6 -- Terminal: start job

Command:

```bash
cambrian pack start "로그인 에러 수정해"
```

Say:

Cambrian does not call the AI provider. It creates a packet and job artifact for the AI you already use.

Hide:

- raw absolute paths

Expected output:

- job id
- packet preview
- next command

## Shot 7 -- AI reply fixture

Show:

- `examples/auth_bug_demo/fixtures/ai_reply_patch_candidate.yaml`
- `response_kind: patch_candidate`

Say:

For reproducibility, this launch run uses a canned AI reply fixture.

Hide:

- unrelated source contents
- private code

Expected output:

- viewer understands this is a reproducible product run, not a provider call.

## Shot 8 -- job ingest and validate

Commands:

```bash
cambrian pack job-ingest <job-id> fixtures/ai_reply_patch_candidate.yaml
cambrian pack job-validate <job-id>
```

Say:

The reply becomes a validation-ready job, then a validated proposal. This is still not source mutation.

Hide:

- excessive raw patch text

Expected output:

- validation-ready state
- validated status
- proposal reference

## Shot 9 -- proof / outcome

Command:

```bash
cambrian pack proof auth-bug-core
```

Say:

Proof starts locally. If evidence is limited, Cambrian says so instead of inventing numbers.

Hide:

- personal paths
- fake metrics

Expected output:

- local proof/outcome summary
- honest known limits

## Closing

Say:

Cambrian turns AI from a chat box into an installable worker pack workflow.
