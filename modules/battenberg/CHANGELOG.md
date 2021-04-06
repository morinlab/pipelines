# Changelog

All notable changes to the `battenberg` module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [1.1] - 2020-12-22

This release was authored by Ryan Morin.
This overhaul began with addition of cram support. This required a new symlink to the bai file with a name that can be found by HTSlib (i.e. .crai). Unfortunately the automatic inference of patient sex was affected by this change because "samtools idxstats" is extremely slow on cram files. To help address the effect of this on performance this step has been placed in a separate rule and writes a small text file to record the inferred sex per patient. calc_sex_status.sh was extended to automatically infer the name of both sex chromosomes from the header, making it optional to specify this. This change also leads to a much simpler config. This version also includes job grouping to allow quick-running rules to be submitted as jobs along with long-running steps (avoiding too many local rules). The Battenberg script in this repo and the forked Battenberg R package were both modified to allow the reference genome fasta file to be specified (needed for CRAM support).

Some other minor changes occur in this version:
-The src directory has a simpler structure (no subdirectories) and this is exported as PATH in some rules to further simplify the config. 
-The newest post-processing script in LCR-scripts is used to properly infer the log-ratio using clonal and subclonal events (this was completely broken in previous versions)

## [1.0] - 2020-06-17

This release was authored by Ryan Morin.

I modified the Battenberg source code to take an optional "chr_prefixed_genome" argument and some modifications to enable battenberg to work with genomes that have "chr" prefixes in the chromosome names. The installation uses conda to create an R installation with all required prerequisites with the exception of ASCAT and Battenberg, which are installed from github. The modified R script that runs the pipeline is bundled with this tool but this may not be necessary for future releases. 

This installation is currently accomplished by a _install_battenberg rule but there is probably a better way (subworkflow?).  
Obtaining and setting up reference directories for Battenberg is CURRENTLY UP TO THE USER. The forked repository (https://github.com/morinlab/battenberg) describes how this can be achieved. I decided to forego auto-installation of references due to some finnicky steps required (e.g. creating a file that includes the full path to each reference file on the local filesystem). I am open to suggestions for how to elegantly handle this annoyance. 

In contrast to the Sequenza module, I haven't embedded cnv2igv.py in the module. Instead, the user must specify the path to their LCR-scripts repository. Similar to my original version of Sequenza, I relied on the calc_sex_status.sh script because it was working. Suggestions for more elegant solutions are welcome. 