#!/usr/bin/env python3
import re
import os
import json
import argparse
from os import listdir
from pathlib import Path
from os.path import isfile, join
from ccc.ccc import get_cc_from_callgrind_file
from collections import OrderedDict, defaultdict

def convert_dict_to_json(raw_dict):
    """
    Converts the non-string keys of the final result dictionary to string ones,
    so that the dict can be dumped as JSON.

    The code of this function is closely tied to the internal representation
    of the final result dict. A change in it, would probably require the
    chagne of this function's code as well.

    NOTE: it's not the most Pythonic or elegant code you will find. It was
    written "just to work".
    """

    def prefix_dict_to_json(prefix, raw_dict):
        prefix_funcs = raw_dict[prefix]
        res_dict = {prefix : {}}

        for key_1, value_1 in prefix_funcs.items():
                res_dict[prefix][key_1] = {}
                for key_2, value_2 in value_1.items():
                    str_key_2 = str(key_2)
                    res_dict[prefix][key_1][str_key_2] = {}
                    for key_3, value_3 in value_2.items():
                        str_key_3 = str(key_3)
                        res_dict[prefix][key_1][str_key_2][str_key_3] = value_3
        return res_dict

    res_dict = {}
    for prefix in ['client', 'server']:
        res = prefix_dict_to_json(prefix, raw_dict)
        res_dict = {**res_dict, **res}
        
    return res_dict


def verbose_print(msg, verbose, end='\n'):
    if verbose:
        print(msg, end=end)

def parse_ciphersuite_names_from_file(ciphers_file_path):
    CIPHER_ID_NAME_REGEX = r'(?P<id>\d+) (?P<name>[^ ]*?)( |$|\r?\n)'
    pattern = re.compile(CIPHER_ID_NAME_REGEX)
    ciphersuite_name = OrderedDict()

    with open(ciphers_file_path, 'r') as ciphers_file:
        lines = ciphers_file.readlines()

        print(f'{ciphers_file_path} has {len(lines)} lines')

        for line in lines:
            if line is os.linesep:
                continue
            res = pattern.search(line)
            id, name = int(res.group('id')), res.group('name')
            ciphersuite_name[id] = name

    return ciphersuite_name

def parse_filenames_list(path):
    CALLGRIND_FILE_REGEX = (fr'(?P<prefix>(client|server))\.callgrind\.out\.(?P<cipher_id>\d+)\.'
                       '(?P<num_bytes_sent>\d+)\.(?P<num_bytes_received>\d+)')
    pattern = re.compile(CALLGRIND_FILE_REGEX)

    all_files = [join(path, f) for f in listdir(path) if isfile(join(path, f))]
    filenames = {
                 'client': {},
                 'server': {}
                }

    for file_name in all_files:
        res = pattern.search(file_name)

        if res is not None:
            prefix = res.group('prefix')
            cipher_id = int(res.group('cipher_id'))
            num_bytes_sent = int(res.group('num_bytes_sent'))
            num_bytes_received = int(res.group('num_bytes_received'))

            file_info_tuple = (file_name, num_bytes_sent, num_bytes_received)

            try:
                filenames[prefix][cipher_id].append(file_info_tuple)
            except KeyError:
                filenames[prefix][cipher_id] = [file_info_tuple]
        else:
            print(f'[!!!] No pattern found for file name {file_name}')

    return filenames

def parse_callgrind_cpu_cycles_from_files(funcs, cipher_id_file, entity):
    profiling = defaultdict(dict) # {function_name : {ciphersuite_id : num_cycles}}
    num_funcs = len(funcs)
    funcs_parsed = 0

    for func in funcs:
        funcs_parsed = 1
        print(f'Parsing for {entity} {func} {funcs_parsed}/{num_funcs}]...')

        for cipher_id, file_name in cipher_id_file.items():
            print(f'\tparsing for ciphersuite {cipher_id}...')
            cipher_id = int(cipher_id)
            num_cycles = get_cc_from_callgrind_file(file_name, func)
            profiling[func][cipher_id] = num_cycles

            print(f'\t\t num cycles: {num_cycles}')

    return profiling

def write_dict_as_json_to_file(raw_dict, file_name):
    json_dict = convert_dict_to_json(raw_dict)
    res = json.dumps(json_dict)
    with open(file_name, 'w') as out_file:
        out_file.write(res)

def parse_cpu_cycles_for_ciphersuite(files_list, ciphersuite_id,
                                     funcs_to_profile, prefix, verbose=False):
    print(f'\tPrasing for {prefix} {ciphersuite_id}...  \t\t ', end='')

    REGEX = fr'{prefix}\.callgrind\.out'
    res = {}

    try:
        cipher_id_files = files_list[ciphersuite_id]
        print(f'{len(cipher_id_files)} callgrind files found')
    except KeyError:
        print(f'\n\t\t[!!!] No files found for ciphersuite id {ciphersuite_id}')
        return {}

    num_funcs_to_prof = len(funcs_to_profile)
    num_funcs_profiled = 0

    for func_name in funcs_to_profile:
        num_funcs_profiled += 1
        verbose_print(f'\t Profiling function {func_name}... ', verbose, end='')

        res[func_name] = {
            ciphersuite_id: {}
        }

        for filename, num_bytes_sent, num_bytes_received in cipher_id_files:
            key = (num_bytes_sent, num_bytes_received)
            num_cpu_cycles = get_cc_from_callgrind_file(filename, func_name)
            res[func_name][ciphersuite_id][key] = num_cpu_cycles

            verbose_print(f'{num_cpu_cycles} CPU cycles for '
                          f'{num_bytes_sent}, {num_bytes_received}\n',
                          verbose)
    return res

def parse_ciphersuites_profiling(ciphersuites, path, cli_funcs, srv_funcs,
                                 verbose=False):
    CLI_PREFIX = 'client'
    SRV_PREFIX = 'server'

    cli_profiling = {}
    srv_profiling = {}

    files_in_dir = parse_filenames_list(path)

    num_files_in_dir = len(files_in_dir[CLI_PREFIX]) + len(files_in_dir[SRV_PREFIX])
    num_cipheruites = len(ciphersuites)

    num_ciphersuites_parsed = 0

    print(f'Begin parsing metrics for {num_cipheruites} ciphersuites. '
           f'Total files: {num_files_in_dir}')

    for ciphersuite_id in ciphersuites:
        num_ciphersuites_parsed += 1
        verbose_print(f'--- Start parsing for ciphsersuite {ciphersuite_id} --- '
              f'[{num_ciphersuites_parsed}/{num_cipheruites}]', verbose)
        # parse metrics for the client
        cli_profiling_for_ciphersuite = parse_cpu_cycles_for_ciphersuite(
                                                                files_in_dir[CLI_PREFIX],
                                                                ciphersuite_id,
                                                                cli_funcs,
                                                                CLI_PREFIX,
                                                                verbose)

        cli_profiling = {**cli_profiling, **cli_profiling_for_ciphersuite}

        # parse metrics for the server
        srv_profiling_for_ciphersuite = parse_cpu_cycles_for_ciphersuite(
                                                                files_in_dir[SRV_PREFIX],
                                                                ciphersuite_id,
                                                                cli_funcs,
                                                                SRV_PREFIX,
                                                                verbose)
        srv_profiling = {**srv_profiling, **srv_profiling_for_ciphersuite}

        verbose_print(f'--- End parsing for ciphsersuite {ciphersuite_id} --- '
              f'[{num_ciphersuites_parsed}/{num_cipheruites}]', verbose)
    print(f'End parsing metrics. {num_ciphersuites_parsed} from {num_files_in_dir} files')
    return cli_profiling, srv_profiling

def run(ciphers_file_path, path, cli_funcs, srv_funcs, out_file_name):
    path = Path(path)

    if not path.is_dir():
        raise Exception('Path argument must point to a directory')

    ciphersuite_name = parse_ciphersuite_names_from_file(ciphers_file_path)
    ciphersuite_order = ciphersuite_name.keys()  # follow the order of the files

    cli_prof, srv_prof = parse_ciphersuites_profiling(ciphersuite_order, path,
                                                      cli_funcs, srv_funcs)

    profiling_res = {'client': cli_prof, 'server': srv_prof}
    write_dict_as_json_to_file(profiling_res, out_file_name)


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description= 'Profiled Encryption Metrics Collector\n'
    'Collect the profiled encryption metrics and save data as JSON.\n'
    'The tool assumes that the files have the following naming::\n'
    '\t[client|server].callgrind.out.<ciphersuite_id>.<num_bytes_sent>.<num_bytes_received>')

    parser.add_argument('ciphers', type=str, help='file containing a list of '
                        'ciphersuite ids and their respective names.'
                        'Each line of the file must have the format: '
                        '<ciphersuite_id> <ciphersuite_name> [arbitrary_info, ...]')
    parser.add_argument('-p', '--path', type=str, default='./', help='path of the callgrind output files')
    parser.add_argument('--sf', nargs='*', default=[], help='name of server functions to profile')
    parser.add_argument('--cf', nargs='*', default=[], help='name of client functions to profile')
    parser.add_argument('-o', '--output', type=str, default=None,
                             help='output JSON file with the profiling results. '
                             'The keys of the ciphersuites are its ids')
    parser.add_argument('-v', '--verbose', action='store_true', default=False,
                        help='enable verbose output')

    args = parser.parse_args()
    run(args.ciphers, args.path, args.cf, args.sf, args.output)