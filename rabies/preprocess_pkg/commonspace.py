from nipype.interfaces import utility as niu
import nipype.interfaces.ants as ants
import nipype.pipeline.engine as pe  # pypeline engine
from nipype.workflows.smri.ants import antsRegistrationTemplateBuildSingleIterationWF
from nipype.interfaces.utility import Function
from nipype.interfaces.base import (
    traits, TraitedSpec, BaseInterfaceInputSpec,
    File, BaseInterface
)


class ANTsDBMInputSpec(BaseInterfaceInputSpec):
    file_list = traits.List(exists=True, mandatory=True,
                            desc="List of anatomical images used for commonspace registration.")
    template_anat = File(exists=True, mandatory=True,
                         desc="Reference anatomical template to define the target space.")
    output_folder = traits.Str(
        exists=True, mandatory=True, desc="Path to output folder.")


class ANTsDBMOutputSpec(TraitedSpec):
    ants_dbm_template = File(
        exists=True, desc="Output template generated from commonspace registration.")


class ANTsDBM(BaseInterface):
    """
    Runs commonspace registration using ants_dbm.
    """

    input_spec = ANTsDBMInputSpec
    output_spec = ANTsDBMOutputSpec

    def _run_interface(self, runtime):
        import os
        import pandas as pd

        # create a csv file of the input image list
        cwd = os.getcwd()
        csv_path = cwd+'/commonspace_input_files.csv'

        from rabies.preprocess_pkg.utils import flatten_list
        merged = flatten_list(list(self.inputs.file_list))
        df = pd.DataFrame(data=merged)
        df.to_csv(csv_path, header=False, sep=',', index=False)

        model_script_path = os.environ["RABIES"] + \
            '/rabies/shell_scripts/ants_dbm.sh'

        template_folder = self.inputs.output_folder+'/ants_dbm_outputs/'

        if os.path.isdir(template_folder):
            print('Previous commonspace_datasink/ants_dbm_outputs/ folder detected. Inputs from a previous run may cause issues for the commonspace registration, so consider removing the previous folder before running again.')
        print('Running commonspace registration.')
        command = 'mkdir -p %s' % (template_folder,)
        from rabies.preprocess_pkg.utils import run_command
        rc = run_command(command)
        command = 'cd %s ; bash %s %s %s' % (
            template_folder, model_script_path, csv_path, self.inputs.template_anat)
        rc = run_command(command)

        # verify that all outputs are present
        ants_dbm_template = template_folder + \
            '/ants_dbm/output/secondlevel/secondlevel_template0.nii.gz'
        if not os.path.isfile(ants_dbm_template):
            raise ValueError(ants_dbm_template+" doesn't exists.")

        i = 0
        for file in merged:
            file = str(file)
            import pathlib  # Better path manipulation
            filename_template = pathlib.Path(file).name.rsplit(".nii")[0]
            anat_to_template_inverse_warp = '%s/ants_dbm/output/secondlevel/secondlevel_%s%s1InverseWarp.nii.gz' % (
                template_folder, filename_template, str(i),)
            if not os.path.isfile(anat_to_template_inverse_warp):
                raise ValueError(
                    anat_to_template_inverse_warp+" file doesn't exists.")
            anat_to_template_warp = '%s/ants_dbm/output/secondlevel/secondlevel_%s%s1Warp.nii.gz' % (
                template_folder, filename_template, str(i),)
            if not os.path.isfile(anat_to_template_warp):
                raise ValueError(anat_to_template_warp+" file doesn't exists.")
            anat_to_template_affine = '%s/ants_dbm/output/secondlevel/secondlevel_%s%s0GenericAffine.mat' % (
                template_folder, filename_template, str(i),)
            if not os.path.isfile(anat_to_template_affine):
                raise ValueError(anat_to_template_affine
                                 + " file doesn't exists.")
            i += 1

        setattr(self, 'ants_dbm_template', ants_dbm_template)

        return runtime

    def _list_outputs(self):
        return {'ants_dbm_template': getattr(self, 'ants_dbm_template')}


# workflow inspired from https://nipype.readthedocs.io/en/latest/users/examples/smri_antsregistration_build_template.html
def init_commonspace_wf(name="antsRegistrationTemplateBuilder"):

    workflow = pe.Workflow(name=name)
    inputnode = pe.Node(niu.IdentityInterface(
        fields=['file_list']), name='inputnode')
    outputnode = pe.Node(niu.IdentityInterface(fields=[
                         'PrimaryTemplate', 'PassiveTemplate', 'Transforms', 'PreRegisterAverage']), name='outputnode')

    datasource = pe.Node(Function(input_names=['InitialTemplateInputs'],
                                  output_names=['InitialTemplateInputs', 'ListOfImagesDictionaries',
                                                'registrationImageTypes', 'interpolationMapping'],
                                  function=prep_data),
                         name='datasource')

    # creates an average from the input images as initial target template
    initAvg = pe.Node(interface=ants.AverageImages(), name='initAvg')
    initAvg.inputs.dimension = 3
    initAvg.inputs.normalize = True

    # Define the iterations for template building
    buildTemplateIteration1 = antsRegistrationTemplateBuildSingleIterationWF(
        'iteration01')
    buildTemplateIteration2 = antsRegistrationTemplateBuildSingleIterationWF(
        'iteration02')
    buildTemplateIteration3 = antsRegistrationTemplateBuildSingleIterationWF(
        'iteration03')

    workflow.connect(inputnode, "file_list", datasource,
                     "InitialTemplateInputs")
    workflow.connect(datasource, "InitialTemplateInputs", initAvg, "images")

    workflow.connect(initAvg, 'output_average_image', buildTemplateIteration1,
                     'inputspec.fixed_image')
    workflow.connect(datasource, 'ListOfImagesDictionaries',
                     buildTemplateIteration1, 'inputspec.ListOfImagesDictionaries')
    workflow.connect(datasource, 'registrationImageTypes', buildTemplateIteration1,
                     'inputspec.registrationImageTypes')
    workflow.connect(datasource, 'interpolationMapping', buildTemplateIteration1,
                     'inputspec.interpolationMapping')

    '''
    #the template created from the previous iteration becomes the new target template
    workflow.connect(buildTemplateIteration1, 'outputspec.template',
                     buildTemplateIteration2, 'inputspec.fixed_image')
    workflow.connect(datasource, 'ListOfImagesDictionaries',
                     buildTemplateIteration2, 'inputspec.ListOfImagesDictionaries')
    workflow.connect(datasource, 'registrationImageTypes', buildTemplateIteration2,
                     'inputspec.registrationImageTypes')
    workflow.connect(datasource, 'interpolationMapping', buildTemplateIteration2,
                     'inputspec.interpolationMapping')
    #the template created from the previous iteration becomes the new target template
    workflow.connect(buildTemplateIteration2, 'outputspec.template',
                     buildTemplateIteration3, 'inputspec.fixed_image')
    workflow.connect(datasource, 'ListOfImagesDictionaries',
                     buildTemplateIteration3, 'inputspec.ListOfImagesDictionaries')
    workflow.connect(datasource, 'registrationImageTypes', buildTemplateIteration3,
                     'inputspec.registrationImageTypes')
    workflow.connect(datasource, 'interpolationMapping', buildTemplateIteration3,
                     'inputspec.interpolationMapping')
    '''

    workflow.connect(buildTemplateIteration1, 'outputspec.template', outputnode,
                     'PrimaryTemplate')
    workflow.connect(buildTemplateIteration1,
                     'outputspec.passive_deformed_templates', outputnode,
                     'PassiveTemplate')
    workflow.connect(buildTemplateIteration1,
                     'outputspec.transforms_list', outputnode,
                     'Transforms')
    workflow.connect(initAvg, 'output_average_image', outputnode,
                     'PreRegisterAverage')

    return workflow


def prep_data(InitialTemplateInputs):
    interpolationMapping = {
        'anat': 'Linear'
    }

    registrationImageTypes = ['anat']

    # create a list of dictionaries of the input files
    ListOfImagesDictionaries = []
    for file in InitialTemplateInputs:
        ListOfImagesDictionaries.append({'anat': file})

    return InitialTemplateInputs, ListOfImagesDictionaries, registrationImageTypes, interpolationMapping
