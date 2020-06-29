//--------------------------------------------------------------------------
/*! \file pre_vars_in_sim_code_event/model.cc

\brief model definition file that is part of the feature testing
suite of minimal models with known analytic outcomes that are used for continuous integration testing.
*/
//--------------------------------------------------------------------------


#include "modelSpec.h"

//----------------------------------------------------------------------------
// Neuron
//----------------------------------------------------------------------------
class Neuron : public NeuronModels::Base
{
public:
    DECLARE_MODEL(Neuron, 0, 2);

    SET_SIM_CODE("$(x)= $(t)+$(shift);\n");

    SET_THRESHOLD_CONDITION_CODE("(fmod($(x),1.0) < 1e-4)");

    SET_VARS({{"x", "scalar"}, {"shift", "scalar"}});
};

IMPLEMENT_MODEL(Neuron);

//----------------------------------------------------------------------------
// WeightUpdateModel
//----------------------------------------------------------------------------
class WeightUpdateModel : public WeightUpdateModels::Base
{
public:
    DECLARE_MODEL(WeightUpdateModel, 1, 1);

    SET_VARS({{"w", "scalar"}});
    SET_PARAM_NAMES({"myTrigger"});

    SET_EVENT_THRESHOLD_CONDITION_CODE("(fmod($(x_pre),$(myTrigger)) < 1e-4)");
    SET_EVENT_CODE("$(w)= $(x_pre);");
};

IMPLEMENT_MODEL(WeightUpdateModel);


void modelDefinition(ModelSpec &model)
{
#ifdef OPENCL_DEVICE
    GENN_PREFERENCES.deviceSelectMethod = DeviceSelect::MANUAL;
    GENN_PREFERENCES.manualDeviceID = OPENCL_DEVICE;
#endif
#ifdef OPENCL_PLATFORM
    GENN_PREFERENCES.manualPlatformID = OPENCL_PLATFORM;
#endif
    model.setDT(0.1);
    model.setName("pre_vars_in_sim_code_event");

    model.addNeuronPopulation<Neuron>("pre", 10, {}, Neuron::VarValues(0.0, uninitialisedVar()));
    model.addNeuronPopulation<Neuron>("post", 10, {}, Neuron::VarValues(0.0, uninitialisedVar()));

    std::string synName= "syn";
    for (int i= 0; i < 10; i++)
    {
        std::string theName= synName + std::to_string(i);
        model.addSynapsePopulation<WeightUpdateModel, PostsynapticModels::DeltaCurr>(
            theName, SynapseMatrixType::DENSE_INDIVIDUALG, i, "pre", "post",
            WeightUpdateModel::ParamValues((double)(2*(i+1))), WeightUpdateModel::VarValues(0.0),
            {}, {});
    }
    model.setPrecision(GENN_FLOAT);
}
