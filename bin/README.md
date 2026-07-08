# bin/

The `cairn` dispatcher lives here. Subcommands:

```
mine | distill | refine                 backfill from past transcripts
review | curate | improve               the ongoing loop
maintain | schedule                     nightly maintenance (improve + age-out)
status | lint | memory                   inspect / validate / bounded memory
pin | unpin | provenance                 skill metadata
install | migrate | uninstall | test     lifecycle
--version | --help
```

`curate` takes `--merge`, `--archive-weak`, `--apply-lifecycle` (preview unless
`--yes`). `cairn` with no arguments prints the banner (`../cairn-logo.txt`).
