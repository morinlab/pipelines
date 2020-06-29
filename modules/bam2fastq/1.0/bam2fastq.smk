#!/usr/bin/env snakemake


##### ATTRIBUTION #####


# Original Author:  Lauren Chong
# Module Author:    Helena Winata
# Contributors:     N/A


##### SETUP #####


# Import package with useful functions for developing analysis modules
import oncopipe as op

# Setup module and store module-specific configuration in `CFG`
# `CFG` is a shortcut to `config["lcr-modules"]["outputs"]`
CFG = op.setup_module(
    name = "outputs",
    version = "1.0",
    # TODO: If applicable, add more granular output subdirectories
    subdirectories = ["inputs", "outputs"],
)

# Define rules to be run locally when using a compute cluster
# TODO: Replace with actual rules once you change the rule names
localrules:
    _bam2fastq_input_bam,
    _bam2fastq_all,


##### RULES #####


# Symlinks the input files into the module results directory (under '00-inputs/')
# TODO: If applicable, add an input rule for each input file used by the module
rule _bam2fastq_input_bam:
    input:
        bam = CFG["inputs"]["sample_bam"]
    output:
        bam = CFG["dirs"]["inputs"] + "bam/{seq_type}--{genome_build}/{sample_id}.bam"
    run:
        op.relative_symlink(input.bam, output.bam)


rule _bam2fastq_run:
    input:
        bam = rules._bam2fastq_input_bam.output.bam
    output:
        fastq = expand("{fq_dir}{{seq_type}}--{{genome_build}}/{{sample_id}}.{read_num}.fastq", fq_dir = CFG["dirs"]["outputs"], read_num = ["read1", "read2"])
    log:
        stdout = CFG["logs"]["outputs"] + "{seq_type}--{genome_build}/{sample_id}/bam2fastq.stdout.log",
        stderr = CFG["logs"]["outputs"] + "{seq_type}--{genome_build}/{sample_id}/bam2fastq.stderr.log"
    params:
        opts = CFG["options"]["bam2fastq"]
    conda:
        CFG["conda_envs"]["picard"]
    threads:
        CFG["threads"]["bam2fastq"]
    resources:
        mem_mb = CFG["mem_mb"]["bam2fastq"]
    shell:
        op.as_one_line("""
        picard -Xmx{resources.mem_mb}m SamToFastq {params.opts}
        I={input.bam} FASTQ=>(gzip > {output.fq[0]}) SECOND_END_FASTQ=>(gzip > {output.fq[1]}) 
        > {log.stdout} &> {log.stderr}
        """)


rule _bam2fastq_all:
    input:
        expand(
            [
                rules._bam2fastq_run.output.fastq,
                # TODO: If applicable, add other output rules here
            ],
            zip,  # Run expand() with zip(), not product()
            seq_type=CFG["samples"]["seq_type"],
            genome_build=CFG["samples"]["genome_build"],
            sample_id=CFG["samples"]["sample_id"])


##### CLEANUP #####


# Perform some clean-up tasks, including storing the module-specific
# configuration on disk and deleting the `CFG` variable
op.cleanup_module(CFG)
