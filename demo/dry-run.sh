#!/bin/bash

# Default to all targets
TARGETS=${@:-all}

snakemake --dryrun --cores 1 --printshellcmds --reason --use-conda $TARGETS
