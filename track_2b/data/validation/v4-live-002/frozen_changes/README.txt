Restore these two files over base commit c115eb4 to reproduce the evaluated working source of
v4-live-002 (the frozen semantic guard). The other source and prompt hashes are in
manifest.json and, normalised for line endings, in ../source-hashes-lf.json.
acceptance.py (cases and expectations), semantics.py, the Judgment Layer
(judgment.py, judgment_policies.json, docs/JUDGMENT-CONTRACT.md) and every prompt file are
byte-identical to base commit c115eb4: this run changed the final guard, not the rubric, the
semantic layer or the prompts. Runtime credentials are not included.
