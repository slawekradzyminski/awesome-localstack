# Mutation Testing Agent Playbook

## The rule

Mutation testing is a feedback sensor for an implementation agent, not the
first command in its edit loop and not an autonomous verdict. Run normal tests
first. Then use a small mutation scope to ask whether those tests would detect
plausible behavioral damage.

## Installed commands

| Repository | Command | Permanent scope |
| --- | --- | --- |
| `test-secure-backend` | `./mvnw -Pmutation-testing test-compile pitest:mutationCoverage` | ten high-value service, auth, traffic, and LLM-handler classes |
| `vite-react-frontend` | `npm run test:mutation` | runtime configuration, SSE, and SSO |
| `jms-email-consumer` | `./mvnw -Pmutation-testing test-compile pitest:mutationCoverage` | JMS configuration, consumer, and renderer |
| `ollama-mock` | `./mvnw -Pmutation-testing test-compile pitest:mutationCoverage` | service and token-stream utilities |

PIT writes HTML/XML under `target/pit-reports`. Stryker writes JSON/HTML under
`reports/mutation`.

## When to run it

1. During ordinary editing, run the smallest relevant unit tests. Do not run
   mutation testing after every save.
2. After the unit suite is green, run the targeted mutation command when the
   change touches the configured scope or its tests.
3. Before an agent hands off a pull request, classify every new survivor on a
   changed high-risk line.
4. Run a wider package scope nightly and a broader trend run weekly. These jobs
   should not block the fast developer loop.

Skip the mutation run for documentation, formatting, generated assets, and
changes outside the configured production scope unless the scope itself needs
to be expanded.

## How an agent should process a report

For each result on a changed or security-critical line:

1. `NO_COVERAGE` / `NoCoverage`: decide whether the execution path is part of
   the supported contract. If yes, add a test that reaches it. If no, record why
   it is outside the selected test level.
2. `SURVIVED` / `Survived`: state the behavioral change introduced by the
   mutant. Write the missing expectation from the requirement or public
   contract, not from the implementation syntax.
3. Run the new test against the original code and rerun mutation testing. The
   work is complete only if the original remains green and the intended mutant
   is killed.
4. Classify leftovers as meaningful missing oracle, equivalent/unobservable,
   diagnostic-only, runner/instrumentation anomaly, or intentionally out of
   scope. Never add a brittle assertion merely to move the percentage.
5. If a survivor contradicts an existing direct assertion, rerun only that
   mutant or line with conservative coverage analysis. Confirm that the mutant
   is actually active before asking the agent to manufacture another test.
6. For time, retries, and concurrency, prefer virtual clocks and controlled
   schedulers. A mutation that exposes an untestable clock is often design
   feedback, not a reason to add a real sleep.

The agent should report mutant location, mutation, risk, test added, and
before/after status. It should not change production behavior solely to silence
an equivalent mutant.

## Quality gates

Start with a semantic pull-request gate:

- no new unclassified survivors on changed lines;
- zero accepted meaningful survivors in authentication, authorization, token
  generation, money, order state, sanitization, and messaging contracts;
- no decrease in the target's mutation score or covered-code test strength
  without an explicit explanation.

Do not turn a global 80% score into the first gate. The current baselines have
different reachability profiles:

| Target | Total score | Covered-code strength |
| --- | ---: | ---: |
| Backend | 89% | 100% |
| Frontend | 82.41% | 84.33% |
| Consumer | 100% | 100% |
| Mock | 87% | 96% |

After two to four weeks of stable runs, a numeric safety floor can sit just
below these baselines—for example 88%, 81%, 95%, and 86% total score
respectively—while the ratchet and high-risk semantic gate remain authoritative.
Raise floors gradually as uncovered supported paths are added. Do not lower a
floor to make a pull request pass.

## Suggested agent instruction

Use this in a task prompt when the change intersects a configured scope:

> Run the normal tests first, then the repository's targeted mutation command.
> Analyze only mutants in changed or high-risk behavior. Separate no-coverage
> paths from surviving assertions. For each meaningful survivor, describe the
> behavioral damage, add a contract-level test that fails on that mutant and
> passes on the original, rerun the mutation command, and report the before/after
> result. Classify equivalent, diagnostic, runner-anomaly, and intentionally
> out-of-scope mutants; validate suspicious survivors with a narrow rerun. Use
> virtual time for temporal behavior. Do not game the score or alter production
> code only to kill a mutant.

## Two layers for agent-heavy development

Keep rule-based and AI-generated mutants as separate layers:

1. PIT/Stryker is the deterministic PR feedback loop. Its survivors can guide
   persistent tests and support a stable ratchet.
2. Concern-specific LLM mutants are a sampled adversarial evaluation for
   nightly, high-risk, or just-in-time runs. They may better resemble semantic
   bugs, but require compilation, duplication, and equivalence filtering.

Always give the test-writing agent the requirement or protected concern as well
as the mutant. A mutant is a counterexample candidate, not the source of truth.
Persist tests that express stable business, security, protocol, or timing
contracts. Ephemeral tests are reasonable for one-off speculative mutants whose
only purpose is to assess a particular change.

The semantic layer is executable in this workspace:

```bash
python3 experiments/llm-mutation/run_lab.py \
  --output experiments/llm-mutation/results/run.json
```

For every LLM-generated patch, require: a stated violated contract, clean patch
application, successful compilation, and a reviewer decision that the behavior
is supported and observably wrong. Compiler failures are invalid mutants, not
kills. Freeze the patch set before asking an agent to strengthen tests, and do
not regenerate easier mutants after seeing results.

The same instruction is now summarized in each repository's `AGENTS.md`, so an
agent operating there can discover the workflow without a bespoke prompt. The
explicit prompt is still useful for high-risk changes or when mutation analysis
is the main purpose of the task.
