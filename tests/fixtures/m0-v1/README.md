# Foundation model qualification fixtures

Backlog 1.1.1.2 freezes 20 cases for model comparisons on the MSI. Atlas and Birch are synthetic coursework projects. Both contain a two-page `handbook.pdf` with deliberately conflicting checkout rules. Each project has eight answerable questions, one question whose tempting answer belongs to the other project, and one with no evidence in either project.

During M0, supply only the active project's entries from `passages.json` with their file and page labels. Once retrieval exists, ingest the corresponding project PDFs through the normal pipeline. The model receives the question text and permitted evidence. Keep the answer key, cross-project passages and previous evaluation conversations out of its prompt.

Score one point for the expected meaning with the correct project, filename and page, or an explicit abstention on a missing-evidence case. An answer copied from the other project is a disclosure regardless of aggregate score. Report the question IDs of misses. Target at least 18/20 and zero cross-project disclosures.

Use a fresh conversation for each case. Record the fixture revision and checksums with model digest, cold/warm timings, context, output budget, power state and peak memory. The two PDF hashes cover their bytes. JSON hashes use sorted keys and compact separators to keep Windows line endings immaterial. Keep this revision fixed across runs; make a new revision if the evaluation content changes.

