#!/usr/bin/env snakemake
# -----------------------------------------------------------------------------
# Author:        Helena Winata
# email/github:  hwinata@bccrc.ca / whelena
# -----------------------------------------------------------------------------
# Input:         {sample_id}.bam  
#
# Output:        {sample_id}/snvs.vcf      
#                {sample_id}/indels.vcf        
#
# Purpose: Processed bam files are converted into mpileup files using samtools.
#          Varscan then call variants (snvs and indels) from mpileup files and store them as VCF files
# Modes: 
#   unpaired: run varscan on unpaired tumour data
#   paired: run varscan on paired tumour-normal or tumour-unmatched normal data
#  -----------------------------------------------------------------------------

import os
import gzip
import modutils as md

##### SETUP #####

CFG = md.setup_module(
    config = config, 
    name = "varscan", 
    version = "1.0",
    subdirs = ["inputs", "mpileup", "varscan", "outputs"],
    req_references = ["genome_fasta"]
)

localrules: 
    _varscan_input, 
    _varscan_output, 
    _varscan_all


##### RULES #####

rule _varscan_input:
    input:
        bam = CFG["inputs"]["sample_bam"]
    output:
        bam = CFG["dirs"]["inputs"] + "{seq_type}--{genome_build}/{sample_id}.bam"
    run:
        md.symlink(input.bam, output.bam)
        md.symlink(input.bam + ".bai", output.bam + ".bai")


rule _varscan_bam2mpu:
    input:
        bam = rules._varscan_input.output.bam
    output:
        mpu = temp(CFG["dirs"]["mpileup"] + "{seq_type}--{genome_build}/{sample_id}.mpileup")
    log:
        CFG["logs"]["mpileup"] + "{seq_type}--{genome_build}/{sample_id}.bam2mpu.stderr.log"
    params:
        opts = CFG["options"]["bam2mpu"],
        fasta  = lambda wildcards: config["reference"][wildcards.genome_build]["genome_fasta"]
    conda:
        CFG["conda_envs"].get("varscan") or "envs/varscan.yaml"
    threads:
        CFG["threads"].get("varscan") or 1
    resources: 
        mem_mb = CFG["mem_mb"].get("varscan") or 6000
    shell:
        md.as_one_line("""
        samtools mpileup {params.opts}
        -f {params.fasta} {input.bam}
        > {output.mpu} 2> {log}
        """)
        

rule _varscan_mpu2vcf_somatic:
    input:
        normalMPU = CFG["dirs"]["mpileup"] + "{seq_type}--{genome_build}/{normal_id}.mpileup",
        tumourMPU = CFG["dirs"]["mpileup"] + "{seq_type}--{genome_build}/{tumour_id}.mpileup"
    output:
        snp = CFG["dirs"]["varscan"] + "{seq_type}--{genome_build}/{tumour_id}--{normal_id}--{pair_status}/snp.vcf",
        indel = CFG["dirs"]["varscan"] + "{seq_type}--{genome_build}/{tumour_id}--{normal_id}--{pair_status}/indel.vcf",
        # dummy cns output to avoid error
        cns = temp(CFG["dirs"]["varscan"] + "{seq_type}--{genome_build}/{tumour_id}--{normal_id}--{pair_status}/cns.vcf")
    log:
        stdout = CFG["logs"]["varscan"] + "{seq_type}--{genome_build}/{tumour_id}--{normal_id}--{pair_status}/varscan_somatic.stdout.log",
        stderr = CFG["logs"]["varscan"] + "{seq_type}--{genome_build}/{tumour_id}--{normal_id}--{pair_status}/varscan_somatic.stderr.log"
    params:
        opts = md.switch_on_wildcard("seq_type", CFG["options"]["somatic"])
    conda:
        CFG["conda_envs"].get("varscan") or "envs/varscan.yaml"
    threads:
        CFG["threads"].get("varscan") or 1
    resources: 
        mem_mb = CFG["mem_mb"].get("varscan") or 5000
    shell:
        md.as_one_line("""
        varscan somatic 
        {input.normalMPU} {input.tumourMPU} 
        --output-snp {output.snp} --output-indel {output.indel}
        {params.opts}
        > {log.stdout} 2> {log.stderr}
        """)


rule _varscan_mpu2vcf_single:
    input:
        tumourMPU = CFG["dirs"]["mpileup"] + "{seq_type}--{genome_build}/{tumour_id}.mpileup"
    output:
        vcf = CFG["dirs"]["varscan"] + "{seq_type}--{genome_build}/{tumour_id}--{normal_id}--{pair_status}/{vcf_name}.vcf"
    log:
        CFG["logs"]["varscan"] + "{seq_type}--{genome_build}/{tumour_id}--{normal_id}--{pair_status}/varscan_{vcf_name}.stderr.log"
    params:
        opts = md.switch_on_wildcard("seq_type", CFG["options"]["unpaired"]),
        cns = md.switch_on_wildcard("vcf_name", {"cns": CFG["options"]["unpaired"]["cns"], "indel": "", "snp": ""})
    conda:
        CFG["conda_envs"].get("varscan") or "envs/varscan.yaml"
    threads:
        CFG["threads"].get("varscan") or 1
    resources: 
        mem_mb = CFG["mem_mb"].get("varscan") or 5000
    shell:
        md.as_one_line("""
        varscan mpileup2{wildcards.vcf_name}
        {input.tumourMPU} {params.opts} {params.cns}
        > {output.vcf} 2> {log}
        """)


rule _varscan_output:
    input: 
        vcf = CFG["dirs"]["varscan"] + "{seq_type}--{genome_build}/{tumour_id}--{normal_id}--{pair_status}/{vcf_name}.vcf"
    output:
        vcf = CFG["dirs"]["outputs"] + "{seq_type}--{genome_build}/{vcf_name}/{tumour_id}--{normal_id}--{pair_status}.{vcf_name}.vcf"
    run:
        md.symlink(input.vcf, output.vcf) 

'''
rule _varscan_all_dispatch:
    input:
        md.switch_on_wildcard("pair_status", {"matched": [CFG["dirs"]["outputs"] + "{seq_type}--{genome_build}/{tumour_id}--{normal_id}--{pair_status}/snp.vcf", "indel": CFG["dirs"]["outputs"] + "{seq_type}--{genome_build}/{tumour_id}--{normal_id}--{pair_status}/indel.vcf"],"unmatched": expand("{dir}/{{seq_type}}--{{genome_build}}/{{tumour_id}}--{{normal_id}}--{{pair_status}}/{vcf_name}.vcf", dir = CFG["dirs"]["outputs"], vcf_name = CFG["inputs"]["unpaired_run"])})
   
    output:
        touch(CFG["dirs"]["outputs"] + "{seq_type}--{genome_build}/{tumour_id}--{normal_id}--{pair_status}.dispatched"
'''


rule _varscan_all:
    input:
        expand(expand("{{dir}}{seq_type}--{genome_build}/{{vcf_name}}/{tumour_id}--{normal_id}--{pair_status}.{{vcf_name}}.vcf", zip,
                    seq_type=CFG["runs"]["tumour_seq_type"],
                    genome_build=CFG["runs"]["tumour_genome_build"],
                    tumour_id=CFG["runs"]["tumour_sample_id"],
                    normal_id=CFG["runs"]["normal_sample_id"],
                    pair_status=CFG["runs"]["pair_status"]),
                vcf_name=["indel", "snp", "cns"],
                dir = CFG["dirs"]["outputs"])


##### CLEANUP #####

md.cleanup_module(CFG)

del CFG