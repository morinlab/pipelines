#!/usr/bin/env snakemake

'''
It will only run through the workflow(eg. capture) sub directory.
'''
##### SETUP #####

import oncopipe as op

SAMPLES = op.load_samples("~/lcr-modules/demo/data/samples.tsv")
GENOME = op.filter_samples(SAMPLES, seq_type = "genome")


##### REFERENCE_FILES WORKFLOW #####


subworkflow reference_files:
    workdir:
        "reference/"
    snakefile:
        "../workflows/reference_files/2.4/reference_files.smk"
    configfile:
        "../workflows/reference_files/2.4/config/default.yaml"


##### CONFIGURATION FILES #####



# Load module-specific configuration
configfile: "../modules/controlfreec/1.1/config/default.yaml"
configfile: "../modules/utils/2.1/config/default.yaml"
configfile: "../modules/picard_qc/1.0/config/default.yaml"
configfile: "../modules/bam2fastq/1.2/config/default.yaml"
#configfile: "../modules/vcf2maf/1.2/config/default.yaml"
configfile: "../modules/sequenza/1.4/config/default.yaml"
configfile: "../modules/bwa_mem/1.1/config/default.yaml"


# Load project-specific config, which includes the shared 
# configuration and some module-specific config updates
configfile: "config.yaml"


##### CONFIGURATION UPDATES #####


# Use all samples as a default sample list for each module
config["lcr-modules"]["_shared"]["samples"] = GENOME

##### MODULE SNAKEFILES #####


# Load module-specific snakefiles

include: "../modules/controlfreec/1.1/controlfreec.smk"
include: "../modules/utils/2.1/utils.smk"
include: "../modules/picard_qc/1.0/picard_qc.smk"
#include: "../modules/vcf2maf/1.2/vcf2maf.smk"
include: "../modules/sequenza/1.4/sequenza.smk"
include: "../modules/bwa_mem/1.1/bwa_mem.smk"
include: "../modules/bam2fastq/1.2/bam2fastq.smk"



##### TARGETS ######

rule all:
    input:
        rules._picard_qc_all.input,
        rules._bam2fastq_all.input,
        rules._sequenza_all.input,
        rules._bwa_mem_all.input,
        rules._controlfreec_all.input,
        #rules._vcf2maf_all.input
