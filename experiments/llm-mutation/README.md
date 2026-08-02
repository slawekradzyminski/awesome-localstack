# LLM Semantic Mutation Lab

This lab evaluates tests against plausible behavioral defects authored by
Codex rather than against PIT/Stryker's fixed operators. Every mutant is a
reviewable patch with an explicit violated contract.

The runner never edits the source repositories. It copies each working tree to
a temporary directory, applies one patch, compiles it, runs the focused normal
tests, records `killed` or `survived`, and deletes the temporary copy.

## Run

From `awesome-localstack`:

```bash
python3 experiments/llm-mutation/run_lab.py \
  --output experiments/llm-mutation/results/run.json
```

Run one or more cases by ID:

```bash
python3 experiments/llm-mutation/run_lab.py \
  frontend-training-sso-any-loopback-port \
  consumer-drops-legacy-fqcn-type-id
```

The default repository locations are sibling checkouts. Change `repository`
in `manifest.json` when using a different workspace layout. Frontend copies
reuse the source checkout's `node_modules` through a read-only-style symlink;
Java copies reuse the local Maven cache.

## Result taxonomy

- `killed`: production compiles and the selected green baseline test fails;
- `survived`: production compiles and the selected test remains green;
- `invalid-noncompiling`: the proposed mutant is not admissible;
- `invalid-patch`: the patch no longer matches the source revision;
- `baseline-failed`: the result would be uninterpretable, so the mutant is not
  scored;
- `test-timeout`: inspect separately; it is evidence of detection only when the
  timeout is caused by the mutant rather than infrastructure.

Compilation failure is not counted as a kill. A surviving mutant is not
automatically a test defect: review the stated contract, confirm the behavior
is observable and supported, and only then add a test.

## Corpus design

The pilot contains eight compile-oriented, semantic changes across backend,
frontend, model mock, and JMS consumer. They model mistakes an implementation
agent could plausibly make: over-generalizing a security rule, clearing state
in the wrong order, confusing transport chunks with protocol events, collapsing
two timing policies, reading the wrong end of a conversation, and dropping a
compatibility alias during cleanup.

This first corpus is explicitly **white-box and test-aware**: Codex had already
worked with these repositories and tests. It is useful as an engineering lab,
but its score is not an unbiased model benchmark. For a controlled article
experiment, use a separate generator context that receives requirements and
production code but not tests or mutation reports. Freeze its compiling,
human-reviewed patches before exposing them to the test-writing agent.

Suggested blind generator instruction:

> From the requirement and production diff, propose one realistic semantic bug
> that could be introduced by an AI coding agent. Prefer a multi-line policy,
> state, ordering, protocol, compatibility, or data-flow mistake over token-level
> operator replacement. Do not inspect tests. Return a minimal patch, the
> violated contract, an example observation distinguishing it from the original,
> and why the change is plausible. The patch must compile.

For a stronger holdout, generate several candidates, reject noncompiling,
duplicate, equivalent, and requirement-invalid cases, and keep the corpus
hidden from the agent that writes or repairs tests.

See [`RESULTS.md`](./RESULTS.md) for the first frozen-corpus run and the
before/after test-strengthening result.
