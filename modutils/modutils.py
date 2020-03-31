# MODULES

import os
import copy
import functools
import itertools
import subprocess
from collections import defaultdict, namedtuple

import yaml
import pandas as pd
import snakemake as smk
from snakemake.logging import logger


# CONSTANTS

LOWERCASE_COLS = ("tissue_status", "seq_type", "ff_or_ffpe")

DEFAULT_PAIRING_CONFIG = {
    "genome": {
        "run_unpaired_tumours_with": "unmatched_normal",
        "run_paired_tumours": True,
        "run_paired_tumours_as_unpaired": False,
    },
    "capture": {
        "run_unpaired_tumours_with": "unmatched_normal",
        "run_paired_tumours": True,
        "run_paired_tumours_as_unpaired": False,
    },
    "mrna": {
        "run_unpaired_tumours_with": "no_normal",
        "run_paired_tumours": False,
        "run_paired_tumours_as_unpaired": True,
    },
    "mirna": {
        "run_unpaired_tumours_with": "no_normal",
        "run_paired_tumours": False,
        "run_paired_tumours_as_unpaired": True,
    },
}


# SESSION


class _Session:
    """Session for storing Snakemake config internally."""

    def __init__(self):
        self.config = None

    def setup_lcr_modules(self, config):
        self.config = config


_session = _Session()


setup_lcr_modules = _session.setup_lcr_modules


# CONVENIENCE FUNCTIONS


def set_input(module, name, value):
    """Use given value as input"""
    config = _session.config
    config["lcr-modules"][module]["inputs"][name] = value


def set_samples(module, *samples):
    """Use given value as input"""
    config = _session.config
    config["lcr-modules"][module]["samples"] = pd.concat(samples)


# UTILITIES


def symlink(src, dest):
    """Creates a relative symlink from any working directory.

    Parameters
    ----------
    src : str
        The source file path.
    dest : str
        The destination file path. This can also be a destination
        directory, and the destination symlink name will be identical
        to the source file name.
    """
    if os.path.isdir(dest):
        dest_dir = dest
        dest_file = os.path.split(src)[1]
    else:
        dest_dir, dest_file = os.path.split(dest)
    src_rel = os.path.relpath(src, dest_dir)
    dest = os.path.join(dest_dir, dest_file)
    os.symlink(src_rel, dest)


def get_from_dict(dictionary, list_of_keys):
    """Access nested index/key in dictionary."""
    return functools.reduce(dict.get, list_of_keys, dictionary)


def collapse(text):
    """Collapses a triple-quoted string to one line.

    Line endings do not need to be escaped like in a shell script.
    Spaces and tabs are stripped from each side of each line to
    remove the indentation included in triple-quoted strings.

    This function is useful for long shell commands in a Snakefile,
    especially if it contains quotes that would need to be escaped
    (e.g., in an awk command).

    Returns
    -------
    str
        A single line (i.e., without line endings) of text.
    """
    lines = text.strip().split("\n")
    lines_dedented = [x.strip(" \t") for x in lines]
    return " ".join(lines_dedented)


def list_files(directory, file_ext):
    """Searches directory for all files with given extension.

    The search is performed recursively. The function first tries
    to use the faster `find` UNIX tool before falling back on a
    slower Python implementation.

    Parameters
    ----------
    directory : str
        The directory to search in.
    file_ext : str
        The file extension (excluding the period).

    Returns
    -------
    list of str
        The list of matching files.
    """

    files_all = []

    try:
        # Get list of BAM files using `find` UNIX tool (fast)
        command = ["find", directory, "-name", f"*.{file_ext}"]
        files = subprocess.check_output(command, text=True)
        files_split = files.rstrip("\n").split("\n")
        files_all.extend(files_split)
    except subprocess.CalledProcessError:
        # Slower fallback in Python
        for root, _subdirs, files in os.walk(directory):
            files = [f for f in files if f.endswith(f".{file_ext}")]
            files = [os.path.join(root, f) for f in files]
            files_all.extend(files)

    return files_all


# SNAKEMAKE INPUT/PARAM FUNCTIONS


def make_seqtype_specific(param_config, spacer=" "):
    """Handles different options for each sequencing data type.

    Parameters
    ----------
    param_config : dict
        The options (values) for each sequencing data type (keys),
        also known as seq_types. Two special keys, '_prefix' and
        '_suffix', can be included to prepend and append options
        shared between seq_types, respectively.
    spacer : str, optional
        The spacer added between the prefix and the seq_type-specific
        option as well as between that and the suffix.

    Returns
    -------
    function
        A Snakemake-compatible parameter function taking wildcards as
        its only argument. This function will return the parameter value
        constructed from the prefix (if any), the seq_type-specific
        option, and the suffix (if any), joined by a spacer.
    """

    def run_seqtype_param(wildcards):
        param = [
            param_config.get("_prefix", ""),
            param_config.get(wildcards.seq_type, ""),
            param_config.get("_suffix", ""),
        ]
        param_str = spacer.join(x for x in param if x != "")
        return param_str

    return run_seqtype_param


def locate_bam(
    bam_directory=None,
    sample_keys=("sample_id", "tumour_id", "normal_id"),
    sample_bams=("sample_bam", "tumour_bam", "normal_bam"),
):
    """Locates BAM file for a given sample ID in a directory.

    This function actually configures another function, which is
    returned to be used by Snakemake.

    Parameters
    ----------
    bam_directory : str, optional
        The directory containing all BAM files. If None is provided,
        then the default value of 'data/' will be used.
    sample_keys : list of str, optional
        The possible wildcards that contain identifiers for samples
        with BAM files.
    sample_bams : list of str, optional
        The respective names for the BAM file located for each sample
        in `sample_keys` in the dictionary returned by the input file
        function. For example, the BAM file for the sample specified
        in 'sample_id' wildcard will be stored under the key
        'sample_bam' in the returned dictionary.

    Returns
    -------
    function
        A Snakemake-compatible input file function taking wildcards as
        its only argument. This function will return a dictionary of
        BAM files for any wildcards appearing in `sample_keys` under
        the corresponding keys specified in `sample_bams`.
    """

    bam_directory = "data/" if bam_directory is None else bam_directory

    assert len(sample_keys) == len(sample_bams)
    key_to_bam = dict(zip(sample_keys, sample_bams))

    # Use [None] to differentiate from the case where no BAM files are found
    bam_files = [None]
    seq_type_memo = dict()

    def locate_bam_custom(wildcards):

        # Retrieve list of BAM files (if not already done)
        if bam_files == [None]:
            del bam_files[0]
            bam_files.extend(list_files(bam_directory, "bam"))

        # Retrieve (or create) BAM files by seq_type
        seq_type = wildcards.seq_type
        if seq_type not in seq_type_memo:
            seq_type_memo[seq_type] = [b for b in bam_files if seq_type in b]
        seqtype_bam_files = seq_type_memo[seq_type]

        # Create dictionary meant for unpacking in Snakemake
        bams = dict()
        for sample_key, sample_id in wildcards.items():
            if sample_key not in sample_keys:
                continue
            matches = [b for b in seqtype_bam_files if sample_id in b]
            assert len(matches) == 1, (
                f"The given sample ID ({sample_id}) and seq_type "
                f"({wildcards.seq_type}) failed to identify a unique "
                f"BAM file in the given directory ({bam_directory}). "
                f"Instead, {len(matches)} matching files were found: "
                f"{', '.join(matches)}"
            )
            bam_name = key_to_bam[sample_key]
            bams[bam_name] = matches[0]

        return bams

    return locate_bam_custom


# SAMPLE PROCESSING


def load_samples(
    file_path, sep="\t", lowercase_cols=LOWERCASE_COLS, renamer=None, **maps
):
    """Loads samples metadata with some light processing.

    The advantage of using this function over `pandas.read_table()`
    directly is that this function processes the data frame as follows:

        1) Forces lowercase for key columns with that expectation.
           These columns are listed in `modutils.LOWERCASE_COLS`.
        2) Renames columns using either a renamer function and/or
           a set of key-value pairs where the values are the
           original names and the keys are the desired names.

    If a renamer function is provided in addition to a set of key-value
    pairs, the renamer function will be used first.

    Parameters
    ----------
    file_path : str
        The path to the tabular file containing the sample metadata
        (including any required columns).
    sep : str, optional
        The column separator.
    lowercase_cols : list of str, optional
        The columns to be forced to lowercase.
    renamer : function or dict-like, optional
        A function that transforms each column name or a dict-like
        object that maps the original names (keys) to the desired
        names (values).
    **maps : key-value pairs, optional
        Pairs that map the original names (keys) to the desired
        names (values).

    Returns
    -------
    pandas.DataFrame
    """
    samples = pd.read_table(file_path, sep=sep)
    if renamer:
        samples.rename(columns=renamer, inplace=True)
    if maps:
        samples.rename(columns=maps, inplace=True)
    for col in lowercase_cols:
        if col not in samples.columns:
            msg = f"The `{col}` column does not exist " "in the samples data frame."
            logger.warning(msg)
            continue
        samples[col] = samples[col].str.lower()
    return samples


def filter_samples(samples, **filters):
    """Subsets for rows with certain values in the given columns.

    Parameters
    ----------
    samples : pandas.DataFrame
        The samples.
    **filters : key-value pairs
        Columns (keys) and the values they need to contain (values).
        Values can either be an str or a list of str.

    Returns
    -------
    pandas.DataFrame
        A subset of rows from the input data frame.
    """
    for column, value in filters.items():
        if isinstance(value, str):
            value = [value]
        samples = samples[samples[column].isin(value)]
    return samples


def group_samples(samples, subgroups):
    """Organizes samples into nested dictionary.

    Parameters
    ----------
    samples : pandas.DataFrame
        The samples.
    subgroups : list of str
        Columns of `samples` by which to organize the samples.
        The order determines the nesting order.

    Returns
    -------
    nested dict
        The number of levels is determined by the list of subgroups.
        The number of 'splits' at each level is based on the number of
        different values in the samples data frame for that column.
        The 'terminal' values are lists of samples, which are stored
        as named tuples containing all metadata for that row.
    """
    assert len(subgroups) > 0, "Need to provide at least one subgroup."
    # Iterate over each row
    samples_dict = dict()
    Sample = None
    for _index, row in samples.iterrows():
        values = []
        # Initialize intermediate subgroups with dictionaries
        parent = samples_dict
        for subgroup in subgroups[:-1]:
            value = row[subgroup]
            if value not in parent:
                parent[value] = {}
            values.append(value)
            parent = get_from_dict(samples_dict, values)
        # Initialize "terminal" subgroups with sets
        value = row[subgroups[-1]]
        values.append(value)
        if value not in parent:
            parent[value] = list()
        # Add sample ID to the "terminal" subgroup
        parent = parent[value]
        if Sample is None:
            Sample = namedtuple("Sample", row.index.tolist())
        sample = Sample(*row)
        assert (
            sample not in parent
        ), f"`{sample}` not unique for these subgroups ({values})."
        parent.append(sample)
    return samples_dict


def generate_runs_for_patient(
    patient_samples,
    run_paired_tumours,
    run_unpaired_tumours_with,
    unmatched_normal=None,
    run_paired_tumours_as_unpaired=False,
):
    """Generates a run for every tumour with and/or without a paired normal.

    Note that 'unpaired tumours' in the argument names and documentation
    refers to tumours without a matched normal sample.

    Parameters
    ----------
    patient_samples : dict
        Lists of sample IDs (str) organized by tissue_status (tumour vs
        normal) for a given patient. The order of the samples in each
        list is irrelevant.
    run_paired_tumours : boolean
        Whether to run paired tumours. Setting this to False is useful
        for naturally unpaired analyses (e.g., for RNA-seq).
    run_unpaired_tumours_with : { None, 'no_normal', 'unmatched_normal' }
        What to pair with unpaired tumours. This cannot be set to None if
        `run_paired_tumours_as_unpaired` is True. Provide value for
        `unmatched_normal` argument if this is set to 'unmatched_normal'.
    unmatched_normal : namedtuple, optional
        The normal sample to be used with unpaired tumours when
        `run_unpaired_tumours_with` is set to 'unmatched_normal'.
    run_paired_tumours_as_unpaired : boolean, optional
        Whether paired tumours should also be run as unpaired
        (i.e., separate from their matched normal sample).
        This is useful for benchmarking purposes.

    Returns
    -------
    dict
        Lists of sample features prefixed with 'tumour_' and 'normal_'
        for all tumours for the given patient. Depending on the argument
        values, tumour-normal pairs may not be matching, and normal
        samples may not be included. The 'pair_status' column specifies
        whether a tumour is paired with a matched normal sample.
    """

    # Check that `run_unpaired_tumours_with` is among possible values
    run_unpaired_tumours_with_options = (None, "no_normal", "unmatched_normal")
    assert run_unpaired_tumours_with in run_unpaired_tumours_with_options, (
        "`run_unpaired_tumours_with` must be one of the values below "
        f"(not `{run_unpaired_tumours_with}`): \n"
        f"{run_unpaired_tumours_with_options}"
    )

    run_unpaired_tumour = run_unpaired_tumours_with is not None

    # Require `run_unpaired_tumour` if `run_paired_tumours_as_unpaired` is True
    assert run_unpaired_tumour or not run_paired_tumours_as_unpaired, (
        "`run_paired_tumours_as_unpaired` was True whereas "
        "`run_unpaired_tumours_with` was None. Please set "
        "`run_unpaired_tumours_with` to 'unmatched_normal' "
        "or 'no_normal'."
    )

    # Check that `unmatched_normal` is given if `run_unpaired_tumours_with` is
    # set to the 'unmatched_normal' mode
    assert (
        run_unpaired_tumours_with != "unmatched_normal" or unmatched_normal is not None
    ), (
        "`run_unpaired_tumours_with` was set to 'unmatched_normal' "
        "whereas `unmatched_normal` was None. For each seq_type, "
        "provide an unmatched normal sample ID in the _shared section "
        "of the modules configuration under `unmatched_normal_id`."
    )

    # Retrieve tumour and normal samples
    runs = defaultdict(list)
    tumour_samples = patient_samples.get("tumour", [])
    tumour_samples += patient_samples.get("tumor", [])
    normal_samples = patient_samples.get("normal", [None])

    # Add an unpaired normal is there isn't one
    if run_paired_tumours_as_unpaired and None not in normal_samples:
        normal_samples.append(None)

    for tumour, normal in itertools.product(tumour_samples, normal_samples):
        # Check for paired samples
        paired = normal is not None
        if paired and run_paired_tumours is False:
            continue
        # Check for unpaired samples
        unpaired = normal is None
        if unpaired and run_unpaired_tumour is False:
            continue
        # Compile features
        tumour = tumour._asdict()
        if normal is None and run_unpaired_tumours_with == "unmatched_normal":
            normal = unmatched_normal._asdict()
            runs["pair_status"].append("unmatched")
        elif normal is None and run_unpaired_tumours_with == "no_normal":
            normal = {key: None for key in tumour.keys()}
            runs["pair_status"].append("no_normal")
        else:
            normal = normal._asdict()
            runs["pair_status"].append("matched")
        for field in tumour.keys():
            runs["tumour_" + field].append(tumour[field])
            runs["normal_" + field].append(normal[field])

    return dict(runs)


def generate_runs_for_patient_wrapper(patient_samples, pairing_config):
    """Runs generate_runs_for_patient based on the current seq_type.

    This function is meant as a wrapper for `generate_runs_for_patient()`,
    whose parameters depend on the sequencing data type (seq_type) of the
    samples at hand. It assumes that all samples for the given patient
    share the same seq_type.

    Parameters
    ----------
    patient_samples : dict
        Same as `generate_runs_for_patient()`.
    pairing_config : nested dict
        The top level is sequencing data types (seq_type; keys) mapped
        to dictionaries (values) specifying argument values meant for
        `generate_runs_for_patient()`. For example:

        {'genome': {'run_unpaired_tumours_with': 'unmatched_normal',
                    'unmatched_normal': Sample(...)},
         'mrna': {'run_paired_tumour': False,
                  'run_unpaired_tumours_with': 'no_normal'}}

    Returns
    -------
    dict
        Same as `generate_runs_for_patient()`.
    """

    seq_type_set = set()
    for samples_list in patient_samples.values():
        seq_type_set.update(s.seq_type for s in samples_list)

    assert len(seq_type_set) == 1, (
        "This function is only meant to be run on groups of samples for a "
        "given patient and a given sequencing data type. The current group "
        f"of samples has the following seq_types: \n    {seq_type_set}"
    )

    seq_type = seq_type_set.pop()
    return generate_runs_for_patient(patient_samples, **pairing_config[seq_type])


def combine_lists(dictionary, as_dataframe=False):
    """Merges lists for matching keys in nested dictionary.

    Parameters
    ----------
    dictionary : dict
        Foo

        {'genome': {'field1': [1, 2, 3],
                    'field2': [4, 5, 6]},
         'mrna': {'field1': [11, 12, 13],
                  'field2': [14, 15, 16]}}

    as_dataframe : boolean, optional
        Whether the return value is coerced to pandas.DataFrame.

    Returns
    -------
    dict or pandas.DataFrame
        The type of the return value depends on `as_dataframe`.
        If `as_dataframe` is False, the output will look like:

        {'field1': [1, 2, 3, 11, 12, 13],
         'field2': [4, 5, 6, 14, 15, 16]}

        If `as_dataframe` is True, the output will look like:

            field1  field2
        0       1       4
        1       2       5
        2       3       6
        3      11      14
        4      12      15
        5      13      16
    """
    combined = defaultdict(list)
    for d in dictionary.values():
        for k, v in d.items():
            combined[k].extend(v)
    combined = dict(combined)
    if as_dataframe:
        combined = pd.DataFrame(combined)
    return combined


def walk_through_dict(
    dictionary, end_fn, max_depth=None, _trace=None, _result=None, **kwargs
):
    """Runs a function at a given level in a nested dictionary.

    If `max_depth` is unspecified, `end_fn()` will be run whenever
    the recursion encounters an object other than a dictionary.

    Parameters
    ----------
    dictionary : foo
        The dictionary to be recursively walked through.
    end_fn : function
        THe function to be run once recursion ends, either at
        `max_depth` or when a non-dictionary is encountered.
    max_depth : int, optional
        How far deep the recursion is allowed to go. By default, the
        recursion is allowed to go as deep as possible (i.e., until
        it encounters something other than a dictionary).
    _trace : tuple, optional
        List of dictionary keys used internally to track nested position.
    _result : dict
        Used internally to pass new dictionaries and avoid changing the
        input dictionary.
    **kwargs : key-value pairs
        Argument values that are passed to `end_fn()`.

    Returns
    -------
    dict
        A processed dictionary. The input dictionary remains unchanged.
    """

    # Define default values
    if max_depth is None:
        max_depth = float("inf")
    if _trace is None:
        _trace = tuple()
    if _result is None:
        _result = dict()

    # If the max_depth is zero, simply run `end_fn()` right away
    if max_depth <= 0:
        return end_fn(dictionary, **kwargs)

    # Iterate over every dictionary key and run `end_fn()` if the value
    # isn't a dictionary and the end depth isn't met. Otherwise, walk
    # through nested dictionary recursively.
    for k, v in dictionary.items():
        # Track nested position
        current_trace = _trace + (k,)
        if isinstance(v, dict) and len(current_trace) < max_depth:
            _result[k] = dict()
            walk_through_dict(v, end_fn, max_depth, current_trace, _result[k], **kwargs)
        else:
            _result[k] = end_fn(v, **kwargs)

    return _result


def generate_runs(
    samples, pairing_config, subgroups=("seq_type", "patient_id", "tissue_status")
):
    """Produces a data frame of tumour runs from a data frame of samples.

    Here, a 'tumour run' can consist of a tumour-only run or
    a paired run. In the case of a paired run, it can either
    be with a matched or unmatched normal sample.

    Parameters
    ----------
    samples : pandas.DataFrame
        The samples.
    pairing_config : dict
        Same as `generate_runs_for_patient_wrapper()`
    subgroups : list of str, optional
        Same as `group_samples()`

    Returns
    -------
    pandas.DataFrame
        The generated runs with columns matching the keys of the
        return value for `generate_runs_for_patient()`.
    """

    # Organize samples by patient and tissue status (tumour vs. normal)
    patients = group_samples(samples, subgroups)

    # Find every possible tumour-normal pair for each patient
    end_depth = len(subgroups) - 1
    runs = walk_through_dict(
        patients,
        generate_runs_for_patient_wrapper,
        end_depth,
        pairing_config=pairing_config,
    )
    while end_depth > 0:
        runs = walk_through_dict(runs, combine_lists, end_depth - 1, as_dataframe=True)
        end_depth -= 1

    # Warn if runs have duplicates
    if any(runs.duplicated()):
        logger.warn("Duplicate runs exist. This probably shouldn't happen.")

    return runs


# MODULE SETUP/CLEANUP


def setup_module(config, name, version, subdirs):
    """Prepares and validates configuration for the given module.

    Parameters
    ----------
    config : dict
        The snakemake configuration dictionary. This should contain
        the module configuration under `config['lcr-modules'][name]`.
    name : str
        The name of the module.
    version : str
        The semantic version of the module.
    subdirs : list of str
        The subdirectories of the module output directory where the
        results will be produced. They will be numbered incrementally
        and created on disk.

    Returns
    -------
    dict
        The module-specific configuration, including any shared
        configuration from `config['lcr-modules']['_shared']`.
    """

    # Ensure minimum version of Snakemake
    smk.utils.min_version("5.0.0")

    # Ensure that the lcr-modules _shared config is loaded
    assert "lcr-modules" in config and "_shared" in config["lcr-modules"], (
        "Shared lcr-modules configuration is not loaded. "
        "See README.md for more information."
    )

    # Ensure that this module's config is loaded
    assert name in config["lcr-modules"], (
        f"The configuration for the `{name}` module is not loaded. "
        "It should be loaded before the module Snakefile (.smk) is "
        "included. See README.md for more information."
    )

    # Get configuration for the given module and create samples shorthand
    mconfig = copy.deepcopy(config["lcr-modules"]["_shared"])
    smk.utils.update_config(mconfig, config["lcr-modules"][name])
    msamples = mconfig["samples"]

    # Find repository and module directories
    repodir = os.path.normpath(mconfig["repository"])
    modsdir = os.path.join(repodir, "modules", name, version)

    # Ensure that common module sub-fields are present
    subfields = ["inputs", "dirs", "conda_envs", "options", "threads", "mem_mb"]
    for subfield in subfields:
        if subfield not in mconfig:
            mconfig[subfield] = dict()

    # Update placeholders in any string in the module-specific config
    def update_placeholders(obj, **placeholders):
        if isinstance(obj, str):
            result = obj
            for placeholder, value in placeholders.items():
                result = result.replace("{" + placeholder + "}", value)
        else:
            result = obj
        return result

    placeholders = {"REPODIR": repodir, "MODSDIR": modsdir}
    mconfig = walk_through_dict(mconfig, update_placeholders, **placeholders)

    # Validate samples data frame
    schemas_dir = os.path.join(modsdir, "schemas")
    schemas = os.listdir(schemas_dir)
    for schema in schemas:
        smk.utils.validate(msamples, schema=os.path.join(schemas_dir, schema))

    # Configure output directory if not specified and create it
    if mconfig["dirs"].get("_parent") is None:
        root_output_dir = mconfig.get("root_output_dir")
        root_output_dir = root_output_dir or "results"
        output_dir = os.path.join(root_output_dir, f"{name}-{version}")
        mconfig["dirs"]["_parent"] = output_dir
    os.makedirs(mconfig["dirs"]["_parent"], exist_ok=True)

    # Update paths to conda environments to be relative to the module directory
    for env_name, env_val in mconfig["conda_envs"].items():
        if env_val is not None:
            mconfig["conda_envs"][env_name] = os.path.relpath(env_val, modsdir)

    # Setup sub-directories
    mconfig = setup_subdirs(mconfig, subdirs)

    # Replace unmatched_normal_ids with unmatched_normals
    Sample = namedtuple("Sample", msamples.columns.tolist())
    pconfig = copy.deepcopy(DEFAULT_PAIRING_CONFIG)
    smk.utils.update_config(pconfig, mconfig.get("pairing_config", {}))
    mconfig["pairing_config"] = pconfig

    for _seq_type, args_dict in pconfig.items():
        if "unmatched_normal" not in args_dict:
            continue
        normal_id = args_dict.pop("unmatched_normal")
        normal_row = msamples[msamples.sample_id == normal_id]
        num_matches = len(normal_row)
        assert num_matches == 1, (
            f"There are {num_matches} samples matching the normal "
            f"ID ({normal_id}) rather than expected (1)"
        )
        args_dict["unmatched_normal"] = Sample(*normal_row.squeeze())

    # Generate runs
    runs = generate_runs(msamples, pconfig)

    # Split runs based on pair_status
    mconfig["runs"] = runs
    mconfig["paired_runs"] = runs[runs.pair_status != "no_normal"]
    mconfig["unpaired_runs"] = runs[runs.pair_status == "no_normal"]

    # Return module-specific configuration
    return mconfig


def setup_subdirs(module_config, subdirs):
    """Numbers and creates module output subdirectories.

    Parameters
    ----------
    module_config : dict
        The module-specific configuration.
    subdirs : list of str
        The name (without numbering) of the output subdirectories.

    Returns
    -------
    dict
        The updated module-specific configuration with the paths
        to the numbered output subdirectories.
    """

    # Check for any issues with the subdirectory names
    assert "_parent" not in subdirs, "You cannot have a '_parent' sub-directory."
    assert subdirs[0] == "inputs", "The first subdirectory must be 'inputs'."
    assert subdirs[-1] == "outputs", "The last subdirectory must be 'outputs'."

    # Generate zero-padded numbers
    numbers = [f"{x:02}" for x in (*range(0, len(subdirs) - 1), 99)]

    # Join numbers and names, and create subdirectory
    parent_dir = module_config["dirs"]["_parent"]
    for num, subdir in zip(numbers, subdirs):
        subdir_full = os.path.join(parent_dir, f"{num}-{subdir}/")
        module_config["dirs"][subdir] = subdir_full
        os.makedirs(subdir_full, exist_ok=True)

    return module_config


def cleanup_module(module_config):
    """Save module-specific configuration, sample, and runs to disk."""

    # Define useful variables
    parent_dir = module_config["dirs"]["_parent"]

    # Define fields to be output as TSV files
    tsv_fields = {
        "samples": None,
        "runs": None,
        "paired_runs": None,
        "unpaired_runs": None,
    }
    tsv_fields_skip = ["paired_runs", "unpaired_runs"]
    for field in tsv_fields.keys():
        tsv_fields[field] = module_config.pop(field)
        if field not in tsv_fields_skip:
            output_file = os.path.join(parent_dir, f"{field}.tsv")
            tsv_fields[field].to_csv(output_file, sep="\t", index=False)

    # Helper function
    def undo_namedtuple(obj):
        if isinstance(obj, tuple) and "sample_id" in obj._asdict():
            result = obj.sample_id
        else:
            result = obj
        return result

    # Output current configuration for future reference
    config_file = os.path.join(parent_dir, "config.yaml")
    with open(config_file, "w") as config_file_handler:
        module_config = walk_through_dict(module_config, undo_namedtuple)
        yaml.dump(module_config, config_file_handler)

    # Add back the TSV fields
    for field in tsv_fields.keys():
        module_config[field] = tsv_fields[field]
