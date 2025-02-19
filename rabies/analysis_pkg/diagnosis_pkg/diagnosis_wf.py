import os
from nipype.pipeline import engine as pe
from nipype.interfaces import utility as niu
from nipype import Function

from rabies.analysis_pkg.diagnosis_pkg.interfaces import ScanDiagnosis, PrepMasks, DatasetDiagnosis
from rabies.analysis_pkg.diagnosis_pkg.diagnosis_functions import temporal_external_formating, spatial_external_formating


def init_diagnosis_wf(analysis_opts, commonspace_bold, preprocess_opts, split_name_list, name="diagnosis_wf"):

    workflow = pe.Workflow(name=name)
    inputnode = pe.Node(niu.IdentityInterface(
        fields=['dict_file', 'analysis_dict']), name='inputnode')
    outputnode = pe.Node(niu.IdentityInterface(fields=['figure_temporal_diagnosis', 'figure_spatial_diagnosis', 
                                                       'analysis_QC', 'temporal_info_csv', 'spatial_VE_nii', 'temporal_std_nii', 'GS_corr_nii', 'GS_cov_nii',
                                                       'CR_prediction_std_nii', 'random_CR_std_nii', 'corrected_CR_std_nii']), name='outputnode')

    if os.path.basename(preprocess_opts.anat_template)=='DSURQE_40micron_average.nii.gz':
        DSURQE_regions=True
    else:
        DSURQE_regions=False

    ScanDiagnosis_node = pe.Node(ScanDiagnosis(prior_bold_idx=analysis_opts.prior_bold_idx,
        prior_confound_idx=analysis_opts.prior_confound_idx,
            NPR_temporal_comp=analysis_opts.NPR_temporal_comp, 
            NPR_spatial_comp=analysis_opts.NPR_spatial_comp, 
            DSURQE_regions=DSURQE_regions),
        name='ScanDiagnosis')

    temporal_external_formating_node = pe.Node(Function(input_names=['temporal_info', 'dict_file'],
                                            output_names=[
                                                'temporal_info_csv'],
                                        function=temporal_external_formating),
                                name='temporal_external_formating')

    spatial_external_formating_node = pe.Node(Function(input_names=['spatial_info', 'dict_file'],
                                            output_names=[
                                                'VE_filename', 'std_filename', 'predicted_std_filename', 'random_CR_std_filename', 'corrected_CR_std_filename', 
                                                'GS_corr_filename', 'GS_cov_filename'],
                                        function=spatial_external_formating),
                                name='spatial_external_formating')
    workflow.connect([
        (inputnode, ScanDiagnosis_node, [
            ("dict_file", "dict_file"),
            ("analysis_dict", "analysis_dict"),
            ]),
        (ScanDiagnosis_node, temporal_external_formating_node, [
            ("temporal_info", "temporal_info"),
            ]),
        (ScanDiagnosis_node, spatial_external_formating_node, [
            ("spatial_info", "spatial_info"),
            ]),
        ])

    workflow.connect([
        (ScanDiagnosis_node, outputnode, [
            ("figure_temporal_diagnosis", "figure_temporal_diagnosis"),
            ("figure_spatial_diagnosis", "figure_spatial_diagnosis"),
            ]),
        (temporal_external_formating_node, outputnode, [
            ("temporal_info_csv", "temporal_info_csv"),
            ]),
        (spatial_external_formating_node, outputnode, [
            ("VE_filename", "spatial_VE_nii"),
            ("std_filename", "temporal_std_nii"),
            ("predicted_std_filename", "CR_prediction_std_nii"),
            ("random_CR_std_filename", "random_CR_std_nii"),
            ("corrected_CR_std_filename", "corrected_CR_std_nii"),
            ("GS_corr_filename", "GS_corr_nii"),
            ("GS_cov_filename", "GS_cov_nii"),
            ]),
        ])

    if (commonspace_bold or preprocess_opts.bold_only) and not len(split_name_list)<3:

        def prep_scan_data(dict_file, analysis_dict, spatial_info):
            import pickle
            with open(dict_file, 'rb') as handle:
                data_dict = pickle.load(handle)

            scan_data={}

            dict_keys = ['temporal_std', 'predicted_std', 'corrected_CR_std', 'random_CR_std', 'GS_corr', 'GS_cov',
                            'DR_BOLD', 'NPR_maps', 'prior_maps' ]
            for key in dict_keys:
                scan_data[key] = spatial_info[key]

            scan_data['FD_trace'] = data_dict['CR_data_dict']['FD_trace']
            scan_data['tDOF'] = data_dict['CR_data_dict']['tDOF']
            scan_data['CR_global_std'] = data_dict['CR_data_dict']['CR_global_std']

            import numpy as np
            import SimpleITK as sitk
            mask_file = data_dict['mask_file']
            mask_img = sitk.ReadImage(mask_file)
            brain_mask = sitk.GetArrayFromImage(mask_img)
            volume_indices = brain_mask.astype(bool)            

            seed_list=[]
            for seed_map in analysis_dict['seed_map_files']:
                seed_list.append(np.asarray(
                    sitk.GetArrayFromImage(sitk.ReadImage(seed_map)))[volume_indices])
            scan_data['seed_list'] = seed_list

            scan_data['name_source'] = data_dict['name_source']
            scan_data['template_file'] = data_dict['template_file']
            scan_data['mask_file'] = data_dict['mask_file']
            return scan_data

        prep_scan_data_node = pe.Node(Function(input_names=['dict_file', 'analysis_dict', 'spatial_info'],
                                            output_names=['scan_data'],
                                        function=prep_scan_data),
                                name='prep_scan_data_node')

        # calculate the number of scans combined in diagnosis
        num_scan = len(split_name_list)
        num_procs = min(analysis_opts.local_threads, num_scan)

        data_diagnosis_split_joinnode = pe.JoinNode(niu.IdentityInterface(fields=['scan_data_list']),
                                                name='diagnosis_split_joinnode',
                                                joinsource='main_split',
                                                joinfield=['scan_data_list'],
                                                n_procs=num_procs, mem_gb=1*num_scan*analysis_opts.scale_min_memory)

        DatasetDiagnosis_node = pe.Node(DatasetDiagnosis(),
            name='DatasetDiagnosis',
            n_procs=num_procs, mem_gb=1*num_scan*analysis_opts.scale_min_memory)
        DatasetDiagnosis_node.inputs.seed_prior_maps = analysis_opts.seed_prior_list
        DatasetDiagnosis_node.inputs.outlier_threshold = analysis_opts.outlier_threshold
        DatasetDiagnosis_node.inputs.network_weighting = analysis_opts.network_weighting

        workflow.connect([
            (inputnode, prep_scan_data_node, [
                ("dict_file", "dict_file"),
                ("analysis_dict", "analysis_dict"),
                ]),
            (ScanDiagnosis_node, prep_scan_data_node, [
                ("spatial_info", "spatial_info"),
                ]),
            (prep_scan_data_node, data_diagnosis_split_joinnode, [
                ("scan_data", "scan_data_list"),
                ]),
            (data_diagnosis_split_joinnode, DatasetDiagnosis_node, [
                ("scan_data_list", "scan_data_list"),
                ]),
            (DatasetDiagnosis_node, outputnode, [
                ("analysis_QC", "analysis_QC"),
                ]),
            ])
    else:
        from nipype import logging
        log = logging.getLogger('nipype.workflow')
        log.warning(
            "Cannot run statistics on a sample size smaller than 3, so dataset diagnosis is not run.")

    return workflow
