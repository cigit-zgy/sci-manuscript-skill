# Architecture contract

The installed package name is `sci_manuscript`, but the repository deliberately omits a `src/sci_manuscript/` directory. `pyproject.toml` maps `src/` directly to that package.

Each lifecycle mutation has exactly one workflow owner. Public API and CLI code may delegate to workflow operations but must not duplicate lifecycle implementations. Domain modules contain state and validation rules. Infrastructure modules contain filesystem primitives and transaction mechanics.
