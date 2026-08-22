# Workflow reference

The lifecycle uses adjacent canonical rounds `r00`, `r01`, `r02`, ... and directories `initial_submission`, `revision_01`, `revision_02`, .... A revision creation manifest records protected source hashes at creation time. Rollback checks against this immutable baseline. Reindex operates transactionally and validates the final gap-free chain plus protected-source hashes before commit.
