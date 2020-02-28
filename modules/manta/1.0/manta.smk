#!/usr/bin/env snakemake

##### MODULES #####

from os.path import join
from snakemake.logging import logger
from modutils import setup_module, generate_pairs, locate_genome_bams


##### SETUP #####

CFG = setup_module(config, "manta", "1.0")
PAIRS = generate_pairs(SAMPLES["manta"])


##### SUBDIRECTORIES #####

CFG["subdir_00"] = join(CFG["output_dir"], "00-input")
CFG["subdir_01"] = join(CFG["output_dir"], "01-manta")
CFG["subdir_99"] = join(CFG["output_dir"], "99-output")


##### RULES #####

rule manta_input:
    input:
        CFG["inputs"].get("sample_bam") or unpack(locate_genome_bams)
    output:
        sample_bam = join(CFG["subdir_00"], "{sample_id}.bam")
    run:
        symlink(input.sample_bam, output.sample_bam)


rule manta_manta:
    input:
        tumour_bam = join(CFG["subdir_00"], "{tumour_id}.bam"),
        normal_bam = join(CFG["subdir_00"], "{normal_id}.bam")
    output:
        vcf = join(CFG["subdir_01"], "{tumour_id}--{normal_id}.vcf")
    params:
        opts = CFG["options"]["manta"]
    shadow:
        "shallow"
    conda:
        CFG["conda_envs"]["manta"] or "envs/manta.yaml"
    shell:
        "echo manta {params.opts} {input.tumour_bam} {input.normal_bam} "
            "> "
        "{output.vcf}"


rule manta_output:
    input:
        vcf = rules.manta_manta.output.vcf
    output:
        vcf = join(CFG["subdir_99"], "{tumour_id}--{normal_id}.vcf")
    run:
        symlink(input.vcf, output.vcf)


rule manta_all:
    input:
        vcfs = expand(rules.manta_manta.output.vcf, zip,
                      tumour_id=PAIRS["tumour"],
                      normal_id=PAIRS["normal"])


##### CLEANUP #####

del CFG
del PAIRS