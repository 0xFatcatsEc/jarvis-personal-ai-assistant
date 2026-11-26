# MSI Thin A15 benchmark report and model selection

**Decision · 23 November 2026.** Select Qwen 3 4B Q4_K_M for the Foundation local profile. Disqualify Qwen 3 8B Q4_K_M for the tested GPU configuration. Backlog 1.1.2.2 and milestone M0 are complete. The existing release manifest already pins the selected build.

## Basis for closure

Backlog 1.1.2.2 requires a measured decision for the selected build after trying 4B first. The Phase 1 technical design calls for an attempt on each candidate, recording deviations, and identifies model-load memory exhaustion as grounds for choosing a smaller profile. The qualification rubric requires 18/20 recall, zero disclosures and warm recall first-text p95 of at most 5 seconds for the selected model. Coding quality informs selection; it has no standalone pass threshold. The owner's conditional instruction authorizes selection on this evidence. All three numerical gates passed without an exception.

## Measured results

Run 02 used Ollama 0.40.17 on the MSI Thin A15 B7UC, RTX 3050 Laptop GPU (4,096 MiB), driver 616.87, AC/Balanced power and VS Code open. Both candidates used the pinned Q4_K_M builds, context 4,096 and output cap 512. Exact digests and fixture hashes are in the [run manifest](run.json).

| Observation | Qwen 3 4B | Qwen 3 8B |
|---|---:|---|
| Cold first visible content / completion | 16.304 / 33.191 s | Load failed |
| Server-reported cold load | 15.779 s | Unmeasured |
| Warm recall first-content median / p95 (20) | 0.336 / 0.584 s | Unmeasured |
| Warm recall completion median / p95 | 14.971 / 33.239 s | Unmeasured |
| Warm coding first-content median / p95 (5) | 0.268 / 0.322 s | Unmeasured |
| Warm coding completion median / p95 | 31.515 / 31.679 s | Unmeasured |
| System RAM baseline / sampled peak | 6,598 / 7,294 MiB | Startup samples only |
| GPU memory baseline / sampled peak | 39 / 2,438 MiB | Startup samples only |
| Grounded recall / cross-project disclosures | 20/20 / 0 | Unscored |
| Coding rubric | 4/10 | Unscored |

Codex reviewed the saved answers against the frozen evidence and coding criteria. All 16 grounded answers supplied the expected fact and page. All four missing-evidence cases abstained. Q19 stated the correct abstention before its reply was cut short. All five coding responses reached the token cap. The model explained several issues correctly, but incomplete implementations cost points. Use 4B as the Foundation baseline; the coding results do not qualify autonomous code editing.

The first-content measurement includes visible deliberation emitted in the answer stream despite the disabled thinking option. The run did not timestamp the transition to the final answer. Use the completion timings to interpret the user experience. System-wide RAM approached the laptop's usable capacity; the recorded figures are sampled peaks. Editor responsiveness was not separately measured. [Raw trials](qwen3-4b/trials.json) · [Resource metrics](qwen3-4b/metrics.json) · [Per-case grades](review.csv)

## Hardware disqualification

The owner supplied the Ollama log excerpt identifying a CUDA out-of-memory error during llama-server startup. The 8B directory contains an environment snapshot and memory samples, with no completed cold trial. This establishes a failed load for this configuration. The 4 GiB capacity alone would not establish incompatibility across CPU-only execution, other offload settings, quantizations or context sizes. Such profiles would require a separate run if pursued. [Disqualification evidence](disqualified.json)

**Remaining M0 work: none.** The collector's original incomplete status records the interrupted paired run. The [adjudicated result](comparison.json) preserves that history and can be regenerated from the repository root with `.venv\Scripts\python.exe -m benchmarks.qualify score outputs/qwen-msi-02`. Run 01's telemetry failure was excluded from the decision.
