# Mutation Testing for Agent-Written Code

Empirical study run on 2026-08-02 against four repositories in the Awesome
Testing stack.

## Implementation follow-up

The proof of concept was subsequently installed in the four repositories. The
production code was not changed: the mutation reports exposed missing proof in
the tests, and the follow-up strengthened those behavioral contracts.

| Repository | Baseline | First feedback round | Final result | Net change |
| --- | --- | --- | --- | --- |
| Backend | 209 killed, 16 survived, 32 no coverage; 81% score / 93% covered strength | 218 / 7 / 32; 85% / 97% | 230 / 0 / 27; 89% / 100% | all 16 covered survivors killed |
| Frontend | 184 killed + 1 timeout, 85 survived, 37 no coverage; 60.26% / 68.52% | 235 + 1 / 62 / 9; 76.87% / 79.19% | 252 + 1 / 47 / 7; 82.41% / 84.33% | 68 additional mutants detected; 30 fewer uncovered |
| Ollama mock | 80 killed, 24 survived, 54 no coverage; 51% / 77% | 87 / 18 / 53; 55% / 83% | 137 / 5 / 16; 87% / 96% | 57 additional mutants killed; 38 fewer uncovered |
| JMS consumer | all seven `JmsConfig` mutants survived | permanent 19-mutant scope: 19 killed, zero survived or uncovered | unchanged: 19 / 0 / 0; 100% / 100% | operational wiring contract added |

The consumer's permanent target is slightly narrower than the exploratory
wildcard, so its generated-mutant total should not be treated as a direct
20-to-19 score comparison. The comparable finding is that every original
`JmsConfig` survivor is now killed.

Concrete improvements:

- refresh-token tests now reject deterministic token generation; removing
  `SecureRandom.nextBytes` no longer passes;
- cart tests prove that both quantity-update paths refresh the catalog price
  and calculate totals from it;
- product tests prove repository deletion, all updateable fields, and a
  non-trivial offset/limit slice;
- frontend tests prove the exact OAuth token-exchange body, PKCE challenge,
  missing-code/verifier/id-token failures, failed exchange behavior, configured
  and fallback logout, social-login verifier, loopback gateway, scope, and
  prompt;
- the JMS consumer now proves that the listener factory is configured and that
  `EmailDto` is serialized as a text message with the producer's type-id
  contract;
- the Ollama mock now proves that non-streaming generation selects the final
  response chunk and that tokenization preserves whitespace and final tokens.
- backend tests now prove password-reset metrics, sanitization and exclusion
  boundaries, blank product names, and all four Boolean input combinations:
  Boolean/string crossed with true/false;
- frontend tests now prove UTF-8 decoding across byte boundaries, multiline and
  empty SSE events, callback cleanup and retry after a transient exchange
  failure, entropy fallback, and optional callback behavior;
- a few mock tests now cover the three public single-response modes and their
  complete supported-prompt fallbacks. That reachability change alone removed
  most of the mock's `NO_COVERAGE` results;
- virtual-time tests prove that ordinary chat/generate chunks use token delay
  and tool-call chunks use their distinct delay, without sleeping or adding
  flakiness.

The last backend pair was particularly instructive. A Boolean `false` test and
a string `"true"` test looked like adequate parser coverage, yet replacement
mutants survived on Boolean `true` and string `"false"`. Adding the complementary
representations killed both, taking covered-code strength to 100%.

The frontend also exposed an important stopping rule. Removing `.trim()` from
two URL inputs still produced the same observable URLs because the `URL`
constructor normalizes surrounding spaces. A narrow Stryker rerun with coverage
optimization disabled produced the same survivors. These are equivalent for
the public result, not an invitation to write implementation-coupled tests.
Several whole-function/static mutants also ran all tests without affecting
direct imports; those should be tracked as runner/instrumentation anomalies
rather than accepted blindly as missing assertions.

These were test-suite defects rather than confirmed production defects. That
is still an important result: before the follow-up, each listed production
behavior could be removed or materially changed while the normal suite stayed
green.

Verification after installation:

- backend: all 429 tests passed; PIT generated 257 mutants, killed all 230
  covered mutants, and completed in 8 seconds of analysis time;
- frontend: all 463 tests and ESLint passed; Stryker ran 43 focused tests
  against 307 mutants in 44 seconds, detecting 253 including one timeout;
- consumer: 11 tests passed; PIT killed all 19 generated mutants in 2 seconds;
- mock: all 37 tests passed; PIT generated 158 mutants, killed 137, and
  completed in 4 seconds. Virtual-time tests added no wall-clock delay.

The operational commands, proposed gates, and agent prompt are documented in
[`MUTATION_TESTING_AGENT_PLAYBOOK.md`](./MUTATION_TESTING_AGENT_PLAYBOOK.md).

## Executive summary

Mutation testing produced useful, actionable information that the existing
green test suites and their conventional coverage reports did not expose.
Across four deliberately scoped samples, the tools generated 742 mutants:

| Repository | Baseline | Scope | Mutants | Killed / timed out | Survived | No coverage | Mutation score | Covered-code test strength |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Backend | 394/394 tests | 10 high-value classes | 257 | 209 | 16 | 32 | 81% | 93% |
| Frontend | 443/443 tests | `runtimeConfig.ts`, `sse.ts`, `sso.ts` | 307 | 185 | 85 | 37 | 60.26% | 68.52% |
| Ollama mock | 23/23 tests | service and token-stream utilities | 158 | 80 | 24 | 54 | 51% | 77% |
| JMS consumer | 8/8 tests | listener, mail, and JMS configuration | 20 | 12 | 7 | 1 | 60% | 63% |
| **Observed total** | **868 passing tests** | heterogeneous samples | **742** | **486** | **132** | **124** | **65.5%** | **78.6%** |

The combined total is an observation, not a leaderboard: PIT and Stryker use
different mutation operators, and each repository sample has a different
shape. The per-repository survivor lists are more useful than the aggregate.

The clearest coverage comparison came from the frontend. Its full suite reports
89.25% line coverage, while the three sampled files report 97.14%, 100%, and
84% line coverage. Their mutation scores were only 76.92%, 61.29%, and 50%,
respectively. High execution coverage did not imply strong assertions.

## Repositories and reproducibility

The experiment used clean, local clones at these revisions:

| Component | Revision |
| --- | --- |
| Backend (`test-secure-backend`) | `aa0b2faae36986fc2015dc0db73e160ad85a3e7b` |
| Frontend (`vite-react-frontend`) | `4dc12f376b2027b108ab2ce914e82fe954ab91b1` |
| Consumer (`jms-email-consumer`) | `e44a97287e513da0351ddc55bc660817f5bf5b47` |
| Model mock (`ollama-mock`) | `a00ad2bb03b53359d66af8f12b293f6fd765f19b` |

Environment:

- Java 25.0.2
- Maven 3.9.16
- Node.js 24.15.0
- Vitest 4.1.10
- PIT 1.25.8 with `pitest-junit5-plugin` 1.2.3
- StrykerJS 9.6.1 with the Vitest runner

The baseline reports were first generated from temporary copies at these
revisions. The implementation follow-up then installed the same scoped PIT and
Stryker configuration, agent instructions, and mutation-driven tests in the
working repositories. Production source files remained unchanged.

### Backend sample

The backend sample covered business logic, authentication controls, traffic
sanitization, and tool-call handlers:

- `ProductService`
- `CartService`
- `OrderService`
- `RefreshTokenService`
- `PasswordResetService`
- `AuthRateLimitGuard`
- `TrafficCapturePolicy`
- `TrafficDataSanitizer`
- `ProductCatalogFunctionHandler`
- `ProductSnapshotFunctionHandler`

PIT initially discovered integration-test classes that are compiled but
excluded from the normal unit-test phase. Those tests failed in PIT's unit-test
environment, so the final run explicitly paired the ten production classes
with their ten green unit-test classes. This is an integration lesson in its
own right: mutation jobs need the same test selection boundaries as CI.

### Frontend sample

The three files were selected because they contain high-value, independently
testable behavior:

- runtime URL and SSO configuration;
- streaming SSE parsing;
- PKCE/SSO login, callback, and logout behavior.

Stryker ran 23 relevant Vitest tests with per-test coverage analysis. One of the
307 mutants timed out and is counted as detected by Stryker.

### Convex/Next.js site

The site was inspected as an additional candidate but not assigned a repository
mutation score. Its baseline had 379 passing tests and one failing content-depth
release gate while the site was actively changing. Mutation scores are not
valid when the selected baseline is red, and user-owned work in progress was
left untouched.

## What the survivors revealed

### Backend: strong suite, specific blind spots

The selected backend tests were the strongest group: 93% test strength for
covered mutants. The 16 survivors were nevertheless valuable:

- cart tests did not detect removal of price updates in two paths;
- product tests did not detect a pagination addition changed to subtraction;
- deletion still passed after the repository `delete` call was removed;
- three product-update field assignments could be removed without failure;
- refresh-token tests did not detect removal of `SecureRandom.nextBytes`, a
  security-critical survivor;
- password-reset metric callbacks could be removed without failure;
- traffic exclusion and body/header sanitization boundary changes survived;
- two tool-call parsing/error predicates could be forced to `true`.

The survivors are not evidence that the implementation is wrong. They show
that the tests do not currently prove those behaviors. For security-sensitive
logic such as token entropy, that distinction is important enough to act on.

### Consumer: context tests did not verify wiring

All seven mutants in `JmsConfig` survived. Tests still passed when PIT removed:

- the JMS message converter from the listener factory;
- the factory configuration call;
- target message type configuration;
- type-id property and mappings;
- both bean return values.

Meanwhile, all five `EmailConsumer` mutants and all seven
`EmailTemplateRenderer` mutants were killed. The business behavior is asserted;
the framework wiring is only instantiated. This is a clean example of a green
Spring context test creating confidence without verifying operational
configuration.

### Ollama mock: reachability dominates the headline score

The mock's headline mutation score was 51%, but covered-code test strength was
77%. Fifty-four mutants had no coverage, concentrated in single-response paths,
scenario aggregation, tool catalog construction, and delay branches.

Important covered survivors included:

- removing reversal of generated chunks;
- changing tokenization and printable-character boundaries;
- changing adaptive-delay predicates;
- weakening supported-prompt formatting.

The right first action is to add tests for the uncovered execution modes, then
work through the meaningful survivors. Chasing the 51% headline alone would
mix these two different jobs.

### Frontend: high coverage concealed weak negative-path oracles

The frontend produced the richest survivor list. Examples include:

- an empty OAuth token-exchange request body still passed;
- missing authorization code, verifier, `id_token`, and failed token response
  checks could be disabled;
- SSO login scope and prompt could become empty;
- the code verifier could become empty on the social-login path;
- logout behavior had no mutation coverage;
- the `127.0.0.1` training gateway branch had no coverage;
- several SSE chunk-boundary and streaming-decoder mutations survived.

Some survivors are low-value or equivalent for the tested inputs, such as
changes to diagnostic log strings, optional chaining where callbacks are always
provided, or trimming that is unobservable without whitespace-heavy inputs.
Stryker's detailed list makes this classification possible; a single score
does not.

## What prior research says

The proposed use in AI development is not speculative. It is an active research
direction:

- Just et al. found a statistically significant relationship between mutant
  detection and real-fault detection independent of code coverage, using 357
  real faults across five open-source programs.
  [FSE 2014 paper](https://homes.cs.washington.edu/~mernst/pubs/mutation-effectiveness-fse2014-abstract.html)
- MuTAP feeds surviving mutants back into LLM prompts. It reported a 93.57%
  mutation score on synthetic buggy code and detected up to 28% more faulty
  human-written snippets than its comparison approaches.
  [MuTAP paper](https://arxiv.org/abs/2308.16557)
- MUTGEN likewise uses iterative mutation feedback for LLM test generation. It
  reports cases with 100% coverage but only 4% mutation score and outperforms
  both EvoSuite and vanilla prompting on 204 subjects.
  [IEEE TSE publication](https://pure.ul.ie/en/publications/mutation-guided-unit-test-generation-with-a-large-language-model/)
- SWE-Mutation treats resistance to mutated solutions as a test-suite benchmark.
  Its 2026 dataset contains 2,636 variants from 800 instances across nine
  languages, and reports that current LLM-generated suites remain insufficiently
  discriminative.
  [ACL 2026 paper](https://aclanthology.org/2026.findings-acl.1976/)
- Work on LLM-generated mutants finds a complementary trade-off: LLM mutants
  can be more diverse and behaviorally closer to real bugs, but have worse
  compilation, duplication, and equivalent-mutant rates than rule-based tools.
  [TOSEM study](https://discovery.ucl.ac.uk/id/eprint/10223970/)
- Meta's Automated Compliance Hardening (ACH) narrows mutation to a specific
  concern, generates a small set of undetected mutants, filters likely
  equivalents, and then asks an LLM for tests. Across 10,795 Kotlin classes it
  generated 9,095 mutants and 571 tests; engineers accepted 73% of surfaced
  tests, with 36% judged privacy-relevant.
  [ACH paper](https://discovery.ucl.ac.uk/id/eprint/10218052/)
- An ICST 2025 approach frames the loop as scientific debugging: hypothesize
  about a surviving mutant, generate a test, observe the result, and refine.
  It outperformed Pynguin on the studied projects, but also made the compute
  cost of iterative LLM calls explicit.
  [Scientific Debugging paper](https://conf.researchr.org/details/icst-2025/mutation-2025-papers/4/Mutation-Testing-via-Iterative-Large-Language-Model-driven-Scientific-Debugging)
- Meta has also described an ephemeral, change-scoped variant: infer the
  intended change, generate concern-specific mutants and tests, use multiple
  assessors, report serious unexpected behavior, then discard the generated
  tests rather than adding maintenance burden. This is an industry design
  proposal, not yet a universal replacement for persistent suites.
  [Meta JiTTesting engineering article](https://engineering.fb.com/2026/02/11/developer-tools/the-death-of-traditional-testing-agentic-development-jit-testing-revival/)
- Intent-based mutation changes a natural-language behavior or specification
  and regenerates code implementing the altered intent. Its evaluation found
  that 55% of generated intent mutants were not subsumed by traditional
  mutations, supporting it as a complementary layer rather than a replacement.
  [Intent-Based Mutation Testing](https://conf.researchr.org/details/icst-2025/mutation-2025-papers/5/Intent-Based-Mutation-Testing-From-Naturally-Written-Programming-Intents-to-Mutants)
- Round-Trip Mutation Testing deliberately introduces code-to-intent-to-code
  mistranslations. On 40 real buggy methods it produced more syntactically
  diverse mutants and, under small selected test budgets, reported over 4x and
  1.7x more detected faults than pattern mutation with 4 and 30 tests.
  [Round-Trip Mutation Testing](https://conf.researchr.org/details/icst-2026/mutation-2026-papers/7/Round-Trip-Mutation-Testing-Translating-Code-to-Natural-Language-Intent-and-back)

These results support two different uses:

1. conventional deterministic mutants as feedback for an AI test-writing agent;
2. later, AI-generated semantic mutants as a more realistic holdout evaluation.

The first should come before the second because it is cheaper, reproducible,
and easier to audit. The strongest architecture is therefore two-layered:

1. **Inner loop:** deterministic PIT/Stryker mutants guide an agent toward
   stronger persistent tests for stable contracts.
2. **Outer loop:** sampled, concern-specific LLM mutants challenge the suite
   with more semantic and realistic faults, either nightly or just in time for
   a risky change.

The mutation report is best understood as an environment signal or verifier
for an agent, not as the specification. The agent still needs the requirement,
public contract, or concern being protected; otherwise it can faithfully encode
the wrong behavior merely to kill a mutant.

## Codex-generated semantic mutant pilot

The follow-up added an executable semantic-mutant lab under
[`experiments/llm-mutation`](../experiments/llm-mutation/README.md). Codex
authored eight frozen, compile-valid patches representing policy, state-order,
transport, timing, conversation, and compatibility misunderstandings. The
runner applies each patch only to a temporary copy, validates the green focused
baseline, compiles the mutant, and classifies the normal suite result.

| Component | Semantic mutants | Initially killed | Initially survived | After focused tests |
| --- | ---: | ---: | ---: | ---: |
| Backend | 2 | 0 | 2 | 2 killed |
| Frontend | 3 | 2 | 1 | 3 killed |
| Ollama mock | 2 | 2 | 0 | 2 killed |
| JMS consumer | 1 | 0 | 1 | 1 killed |
| **Total** | **8** | **4** | **4** | **8 killed** |

The initial survivors were meaningful:

- a partially migrated account was incorrectly treated as SSO-only and denied
  local password reset;
- authenticated email/QR traffic was double-counted against user and IP rate
  limits;
- training SSO was implicitly enabled on every loopback port rather than only
  the designated gateway;
- the legacy fully-qualified JMS producer type identifier was removed while a
  serialization-only test still passed.

Four contract-level tests killed the frozen survivors. The striking result is
that the backend had 100% PIT strength for covered mutants before both semantic
backend mutants survived. The measures are not contradictory: traditional
operators provide strong local perturbation coverage, while intent mutants can
change policy across several otherwise valid statements and states.

The pilot also showed transfer. Tests originally added in response to ordinary
mutants killed four new semantic patches involving retry state, SSE buffering,
virtual timing, and multi-turn direction. Framework mutation can therefore
produce tests useful beyond its own operator vocabulary.

This eight-case result must not be presented as a general LLM benchmark. Codex
had already seen the suites, so generation was white-box and test-aware. A
controlled follow-up should generate and human-review a blind corpus from
requirements plus production code, freeze it, and keep a second holdout hidden
from the test-repair agent. Full results and limitations are in
[`RESULTS.md`](../experiments/llm-mutation/RESULTS.md).

## Recommended agent workflow

Mutation testing should be a feedback sensor, not an autonomous judge:

1. An implementation agent writes code and tests from the requirement.
2. Normal checks run first: format, lint, typecheck, unit tests, and coverage.
3. PIT or Stryker mutates only changed production files or a risk-selected
   package.
4. The system separates `NO_COVERAGE` from `SURVIVED`.
5. A test-focused agent receives one meaningful survivor at a time, plus the
   requirement and public contract. It should not merely copy the implementation.
6. The new test must fail against the mutant and pass against the original.
7. A human or reviewer agent classifies remaining survivors as missing oracle,
   equivalent/inconsequential, or intentionally untested.
8. A broader package or repository run happens nightly or weekly.

This loop is useful in an agent-heavy codebase because generation is cheap but
independent evidence is still scarce. A passing test written by the same model
from the same implementation context can reproduce the implementation's
assumptions. A mutant supplies an adversarial, deterministic counterexample.

## Adoption proposal for this stack

Do not begin with a global 80% gate. The current samples show that repository
shape matters too much.

Start with:

- diff-scoped mutation runs on pull requests, limited to 5-10 minutes;
- no new meaningful survivors in authentication, token, authorization,
  sanitization, money, and order-state logic;
- a ratchet rule: covered-code mutation strength must not fall for changed
  classes;
- explicit integration tests for configuration wiring, where unit mutation is
  otherwise misleading;
- nightly package-level jobs and a weekly broader trend report;
- archived JSON/XML reports so an agent can work from exact mutant IDs rather
  than prose summaries.

Suggested first permanent targets:

| Repository | First target | Reason |
| --- | --- | --- |
| Backend | auth/token, cart/order/product, sanitization | high consequence and already fast |
| Frontend | SSO and SSE libraries | high coverage but many meaningful survivors |
| Consumer | `JmsConfig` integration contract | all seven wiring mutants survived |
| Mock | single-response paths and token utilities | large uncovered region plus boundary survivors |

## A controlled follow-up experiment

The present study measures existing suites. It cannot attribute test quality to
human or agent authorship. To test the AI-specific hypothesis, run a randomized
evaluation with the same implementation tasks and three conditions:

- **A — coverage feedback:** agent writes tests and sees ordinary coverage;
- **B — mutation feedback:** same agent and budget, plus one mutation-feedback
  iteration;
- **C — independent defender:** a separate test agent receives requirements and
  survivor diffs, without the implementation agent's hidden reasoning.

Use a frozen holdout set that the agents never see. It should combine:

- conventional unseen mutants;
- hand-reviewed semantic or higher-order mutants;
- replayable historical bugs where available.

Measure:

- baseline compile and pass rate;
- mutation score on the unseen holdout set;
- historical/seeded real-bug detection;
- number and readability of added tests;
- runtime, model tokens, and monetary cost;
- flake rate across repeated runs;
- maintenance success after a requirement-preserving refactor.

Without a holdout set, an agent can overfit to the exact mutants it was shown.
Without real or semantic bugs, the study can optimize for a mutator rather than
for product risk.

## Post thesis

A strong post can make this argument:

> When agents make code and tests abundant, coverage becomes less scarce and
> independent evidence becomes more valuable. Mutation testing turns a test
> suite from a generated artifact into a falsifiable claim: if this small defect
> were present, would the suite notice?

The stack results keep that thesis grounded: 868 tests were green and reported
high coverage, yet 132 covered mutants survived. The productive conclusion is
not that the suites are bad. It is that mutation feedback identifies exactly
where the next testing effort—and the next agent iteration—has the highest
information value.

The follow-up makes the claim stronger: without changing production code, the
agent killed every covered backend mutant, raised the frontend score by 22.15
points, and raised the mock by 36 points. More importantly, the surviving set
became qualitatively better: mostly equivalent URL normalization, diagnostic
branches, static-instrumentation anomalies, and a few empty-section boundaries.
The useful stopping condition is therefore not 100%; it is the point at which
all remaining mutants are understood and none represents unproved high-risk
behavior.
