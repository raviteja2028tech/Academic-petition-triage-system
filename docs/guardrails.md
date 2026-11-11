# Guardrails — what exists, what it does not do

**These are heuristics plus structural controls. They reduce risk and make failures visible; none of them proves an input or output is safe,
and no claim is made that the detectors stop every attack.**

## Structural controls (the part that does not depend on pattern matching)
| Control | Where | Effect |
|---|---|---|
| Petition text is data | prompts say so; the petition is embedded as JSON (quotes/newlines escaped), never concatenated into instructions | an attacker cannot terminate the data block by typing a delimiter |
| Tool allow-list + validated arguments | `guardrails/tool_args.py`, enforced in `agents/tools.py` before execution | unknown tools, unknown arguments, oversized strings, malformed clause ids, `k` out of 1–8, bad `topic` are refused and reported to the model; recorded in `run_events` |
| Schema validation | Pydantic models for every agent output (`agents/state.py`) with one repair retry, then `invalid_agent_output` escalation | free-form model output never reaches the result |
| Citation verification | `agents/citations.py` | a citation must reference evidence retrieved in this run, match its clause, quote verbatim, and match the live index |
| Authority rule | `agents/verifier_agent.py` | a grant resting on an "may be condoned by …" passage is downgraded to referral |
| Final-decision filter | `agents/policy.py::FINAL_DECISION` | wording like "hereby approved" → `output_blocked` |
| Escalate on failure | every path above | a failed safety/verification check ends in a human-decision escalation with `NO_DETERMINATION`, never a confident answer |

## Heuristic detectors
* **Prompt-injection detection** (`guardrails/injection.py`): normalises text (NFKC, zero-width removal, case-fold, leetspeak mapping) then matches 10 pattern
  families — ignore/override instructions, "new instructions", role override, prompt exfiltration, forced outcome ("mark as approved"), fake authority,
  jailbreak terms, delimiter smuggling (`</petition_text>`, `<|im_start|>`, `[INST]`), tool manipulation, schema hijack (`{"route": …}`). Applied to the petition text
  **before any LLM call**; a hit escalates with reason `unsafe_input` and the text is not sent to a model. 12 attack strings and 5 benign petitions are tested.
* **Toxicity baseline** (`guardrails/toxicity.py`): a small abuse lexicon + threat patterns; no ML model is bundled. Applied to petition text (input) and to
  model-written position/basis/escalation detail (output; a hit → `output_blocked`).
* **Output leak check**: system-prompt phrases in model output (`you are the verifier`, `reply with one json`) → `output_blocked`.
* **Numeric-claim check** (`guardrails/numeric.py`): for decisive routes (`reject`, `grant-under-provision`) every percentage the model states must be traceable
  to cited text, the petition's attendance figure, or a difference/sum of those. Otherwise the verifier treats it as a verification failure (retry, then escalate).
  This addresses "a citation exists" ≠ "the cited text supports the conclusion" only partially, for numbers.

## Added in the final maintenance pass
* **Retrieved text is untrusted.** Each retrieved passage is scanned with the instruction-like pattern subset (`PASSAGE_PATTERNS`); a hit is withheld from the model and the evidence set and recorded as a `guardrail` event (`stage: retrieved_passage`). Tested with a poisoned retriever, and verified to flag **zero** of the real corpus chunks. It cannot detect subtle or paraphrased instructions.
* **New pattern:** attempts to switch off safety steps ("do not escalate", "never verify", "stop referring…"). Live check: such a petition escalates as `unsafe_input`.
* **Deterministic text-vs-field check:** percentages a student states about *their own* attendance are extracted by regex and compared with the structured figure (flag → `petition_inconsistent`); phrases about the rule ("minimum attendance of 85 %") are ignored. Limits: it misses a claim worded unusually or sharing a sentence with a rule phrase, and does not read numbers written as words.
* **Ambiguity:** triage confidence below `TRIAGE_MIN_CONFIDENCE` (0.5) escalates as `petition_ambiguous` ("clarification needed") before any retrieval. The confidence value comes from the model, so a real LLM may be over- or under-confident; the scripted stub uses a keyword rule.

## Known limits (do not oversell)
* Pattern matching is evaded by paraphrase, other languages, encodings, or splitting an instruction across fields. Leetspeak/zero-width handling is best effort.
* False positives are possible (the system escalates a legitimate petition containing e.g. "act as" or abusive words); the cost is a human reads it.
* Retrieved passages are **not** scanned for injection (the corpus is the university's own document, ingested by the operator). A poisoned corpus is out of scope.
* The toxicity lexicon misses sarcasm, implicit abuse and non-English text.
* The numeric check ignores non-percentage figures and does not check legal logic.
* Guardrails apply to petition text; the other petition fields are validated by schema/regex at the API boundary.
* Tracing/logging: span attributes and log fields exclude petition text and credentials by construction and by a redaction filter (tested), but model-written queries and
  clause ids are logged.
* `GUARDRAILS_ENABLED=false` switches the detectors off (used in a test to show the comparison); the structural controls stay on.
