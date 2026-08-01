# Local pattern overrides

Anything here wins over the cached copy from the Fabric repo.

    patterns/extract_insights/system.md    <- overrides the upstream pattern
    patterns/my_own_pattern/system.md      <- a pattern of your own

Reference it by directory name in `config.yaml`:

    pattern: my_own_pattern

An optional `user.md` in the same directory is prepended to the article text.
Fabric's own patterns end with a `# INPUT` marker; yours does not have to.
