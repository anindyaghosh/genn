import numpy as np
import pytest
from pygenn import types

from pygenn import GeNNModel
from pygenn.genn import VarAccess, VarAccessMode

from scipy.special import softmax
from pygenn import (create_current_source_model, 
                    create_custom_update_model,
                    create_neuron_model,
                    create_postsynaptic_model,
                    create_weight_update_model,
                    create_var_ref,
                    create_psm_var_ref,
                    create_wu_var_ref,
                    create_wu_pre_var_ref,
                    create_wu_post_var_ref,
                    init_sparse_connectivity,
                    init_toeplitz_connectivity,
                    init_var)

reduction_neuron_model = create_neuron_model(
    "reduction_neuron",
    var_name_types=[("X", "scalar", VarAccess.READ_ONLY_DUPLICATE), ("Y", "scalar", VarAccess.READ_ONLY_DUPLICATE)])

neuron_model = create_neuron_model(
    "neuron",
    var_name_types=[("X", "scalar", VarAccess.READ_ONLY_DUPLICATE), ("XShared", "scalar", VarAccess.READ_ONLY_SHARED_NEURON)])

static_pulse_duplicate_model = create_weight_update_model(
    "static_pulse_duplicate",
    var_name_types=[("g", "scalar", VarAccess.READ_ONLY_DUPLICATE)],
    sim_code=
    """
    addToPost(g);
    """)

current_source_model = create_current_source_model(
    "current_source",
    var_name_types=[("X", "scalar", VarAccess.READ_ONLY_DUPLICATE), ("XShared", "scalar", VarAccess.READ_ONLY_SHARED_NEURON)])

weight_update_model = create_weight_update_model(
    "weight_update",
    var_name_types=[("X", "scalar", VarAccess.READ_ONLY_DUPLICATE)],
    pre_var_name_types=[("preX", "scalar", VarAccess.READ_ONLY_DUPLICATE), ("preXShared", "scalar", VarAccess.READ_ONLY_SHARED_NEURON)],
    post_var_name_types=[("postX", "scalar", VarAccess.READ_ONLY_DUPLICATE), ("postXShared", "scalar", VarAccess.READ_ONLY_SHARED_NEURON)])

postsynaptic_update_model = create_postsynaptic_model(
    "postsynaptic_update",
    var_name_types=[("psmX", "scalar", VarAccess.READ_ONLY_DUPLICATE), ("psmXShared", "scalar", VarAccess.READ_ONLY_SHARED_NEURON)])

custom_update_model = create_custom_update_model(
    "custom_update",
    var_name_types=[("X", "scalar", VarAccess.READ_ONLY_DUPLICATE)],
    var_refs=[("R", "scalar")])

set_time_custom_update_model = create_custom_update_model(
    "set_time_custom_update",
     update_code=
     """
     V = t;
     R = t;
     """,
     var_name_types=[("V", "scalar")],
     var_refs=[("R", "scalar", VarAccessMode.READ_WRITE)])

set_time_shared_custom_update_model = create_custom_update_model(
    "set_time_custom_update",
     update_code=
     """
     R = t;
     """,
     var_refs=[("R", "scalar", VarAccessMode.READ_WRITE)])
 
softmax_1_custom_update_model = create_custom_update_model(
    "softmax_1",
    update_code=
    """
    MaxX = X;
    """,
    var_name_types=[("MaxX", "scalar", VarAccess.REDUCE_NEURON_MAX)],
    var_refs=[("X", "scalar", VarAccessMode.READ_ONLY)])

softmax_2_custom_update_model = create_custom_update_model(
    "softmax_2",
    update_code=
    """
    SumExpX = exp(X - MaxX);
    """,
    var_name_types=[("SumExpX", "scalar", VarAccess.REDUCE_NEURON_SUM)],
    var_refs=[("X", "scalar", VarAccessMode.READ_ONLY),
              ("MaxX", "scalar", VarAccessMode.READ_ONLY)])

softmax_3_custom_update_model = create_custom_update_model(
    "softmax_3",
    update_code=
    """
    Y = exp(X - MaxX) / SumExpX;
    """,
    var_refs=[("X", "scalar", VarAccessMode.READ_ONLY),
              ("MaxX", "scalar", VarAccessMode.READ_ONLY),
              ("SumExpX", "scalar", VarAccessMode.READ_ONLY),
              ("Y", "scalar", VarAccessMode.READ_WRITE)])

@pytest.mark.parametrize("backend", ["single_threaded_cpu", "cuda"])
@pytest.mark.parametrize("precision", [types.Double, types.Float])
def test_custom_update(backend, precision):
    model = GeNNModel(precision, "test_custom_update", backend=backend)
    model.dt = 1.0
    
    # Create a variety of models to attach custom updates to
    ss_pop = model.add_neuron_population("SpikeSource", 10, "SpikeSource", {}, {});
    n_pop = model.add_neuron_population("Neurons", 100, neuron_model, 
                                        {}, {"X": 0.0, "XShared": 0.0})
    cs = model.add_current_source("CurrentSource", current_source_model, n_pop,
                                  {}, {"X": 0.0, "XShared": 0.0})
    
    dense_s_pop = model.add_synapse_population(
        "DenseSynapses", "DENSE", 0,
        ss_pop, n_pop,
        weight_update_model, {}, {"X": 0.0}, {"preX": 0.0, "preXShared": 0.0}, {"postX": 0.0, "postXShared": 0.0},
        postsynaptic_update_model, {}, {"psmX": 0.0, "psmXShared": 0.0})
    sparse_s_pop = model.add_synapse_population(
        "SparseSynapses", "SPARSE", 0,
        ss_pop, n_pop,
        weight_update_model, {}, {"X": 0.0}, {"preX": 0.0, "preXShared": 0.0}, {"postX": 0.0, "postXShared": 0.0},
        "DeltaCurr", {}, {},
        init_sparse_connectivity("FixedNumberPostWithReplacement", {"rowLength": 10}))
    
    conv_params = {"conv_kh": 3, "conv_kw": 3,
                   "conv_ih": 10, "conv_iw": 10, "conv_ic": 1,
                   "conv_oh": 10, "conv_ow": 10, "conv_oc": 1}
    kernel_s_pop = model.add_synapse_population(
        "ToeplitzSynapses", "TOEPLITZ", 0,
        ss_pop, n_pop,
        weight_update_model, {}, {"X": 0.0}, {"preX": 0.0, "preXShared": 0.0}, {"postX": 0.0, "postXShared": 0.0},
        "DeltaCurr", {}, {},
        init_toeplitz_connectivity("Conv2D", conv_params))
    
    cu = model.add_custom_update(
        "CustomUpdate", "Test", custom_update_model,
         {}, {"X": 0.0}, {"R": create_var_ref(n_pop, "X")})
    dense_cu = model.add_custom_update(
        "DenseCustomUpdate", "Test", custom_update_model,
         {}, {"X": 0.0}, {"R": create_wu_var_ref(dense_s_pop, "X")})
    sparse_cu = model.add_custom_update(
        "SparseCustomUpdate", "Test", custom_update_model,
         {}, {"X": 0.0}, {"R": create_wu_var_ref(sparse_s_pop, "X")})
 
    # Create set time custom updates
    set_time_n = model.add_custom_update("NeuronSetTime", "Test", set_time_custom_update_model,
                                         {}, {"V": 0.0}, {"R": create_var_ref(n_pop, "X")})
    model.add_custom_update("NeuronSharedSetTime", "Test", set_time_shared_custom_update_model,
                            {}, {}, {"R": create_var_ref(n_pop, "XShared")})
    set_time_cs = model.add_custom_update("CurrentSourceSetTime", "Test", set_time_custom_update_model,
                                          {}, {"V": 0.0}, {"R": create_var_ref(cs, "X")})
    model.add_custom_update("CurrentSourceSharedSetTime", "Test", set_time_shared_custom_update_model,
                            {}, {}, {"R": create_var_ref(cs, "XShared")})
    set_time_psm_dense = model.add_custom_update("PSMDenseSetTime", "Test", set_time_custom_update_model,
                                                 {}, {"V": 0.0}, {"R": create_psm_var_ref(dense_s_pop, "psmX")})
    model.add_custom_update("PSMDenseSharedSetTime", "Test", set_time_shared_custom_update_model,
                            {}, {}, {"R": create_psm_var_ref(dense_s_pop, "psmXShared")})
    set_time_wu_pre_dense = model.add_custom_update("WUPreDenseSetTime", "Test", set_time_custom_update_model,
                                                    {}, {"V": 0.0}, {"R": create_wu_pre_var_ref(dense_s_pop, "preX")})
    model.add_custom_update("WUPreDenseSharedSetTime", "Test", set_time_shared_custom_update_model,
                            {}, {}, {"R": create_wu_pre_var_ref(dense_s_pop, "preXShared")})
    set_time_wu_post_dense = model.add_custom_update("WUPostDenseSetTime", "Test", set_time_custom_update_model,
                                                     {}, {"V": 0.0}, {"R": create_wu_post_var_ref(dense_s_pop, "postX")})
    model.add_custom_update("WUPostDenseSharedSetTime", "Test", set_time_shared_custom_update_model,
                            {}, {}, {"R": create_wu_post_var_ref(dense_s_pop, "postXShared")})
    set_time_cu = model.add_custom_update("CUSetTime", "Test", set_time_custom_update_model,
                                          {}, {"V": 0.0}, {"R": create_var_ref(cu, "X")})

    # Create set time custom updates on synapse variables
    set_time_wu_dense = model.add_custom_update("WUDenseSetTime", "Test", set_time_custom_update_model,
                                                {}, {"V": 0.0}, {"R": create_wu_var_ref(dense_s_pop, "X")})
    set_time_wu_sparse = model.add_custom_update("WUSparseSetTime", "Test", set_time_custom_update_model,
                                                 {}, {"V": 0.0}, {"R": create_wu_var_ref(sparse_s_pop, "X")})
    set_time_wu_kernel = model.add_custom_update("WUKernelSetTime", "Test", set_time_custom_update_model,
                                                 {}, {"V": 0.0}, {"R": create_wu_var_ref(kernel_s_pop, "X")})
    set_time_cu_dense = model.add_custom_update("CUDenseSetTime", "Test", set_time_custom_update_model,
                                                {}, {"V": 0.0}, {"R": create_wu_var_ref(dense_cu, "X")})
    set_time_cu_sparse = model.add_custom_update("CUSparseSetTime", "Test", set_time_custom_update_model,
                                                 {}, {"V": 0.0}, {"R": create_wu_var_ref(sparse_cu, "X")})

    # Build model and load
    model.build()
    model.load()
    
    # Simulate 20 timesteps
    samples = [
        (n_pop, "X", n_pop.vars, (100,)),
        (set_time_n, "V", set_time_n.vars, (100,)),
        (n_pop, "XShared", n_pop.vars, (1,)),
        (cs, "X", cs.vars, (100,)),
        (set_time_cs, "V", set_time_cs.vars, (100,)),
        (cs, "XShared", cs.vars, (1,)),
        (dense_s_pop, "psmX", dense_s_pop.psm_vars, (100,)),
        (set_time_psm_dense, "V", set_time_psm_dense.vars, (100,)),
        (dense_s_pop, "psmXShared", dense_s_pop.psm_vars, (1,)),
        (dense_s_pop, "preX", dense_s_pop.pre_vars, (10,)),
        (set_time_wu_pre_dense, "V", set_time_wu_pre_dense.vars, (10,)),
        (dense_s_pop, "preXShared", dense_s_pop.pre_vars, (1,)),
        (dense_s_pop, "postX", dense_s_pop.post_vars, (100,)),
        (set_time_wu_post_dense, "V", set_time_wu_post_dense.vars, (100,)),
        (dense_s_pop, "postXShared", dense_s_pop.post_vars, (1,)),
        (cu, "X", cu.vars, (100,)),
        (set_time_cu, "V", set_time_cu.vars, (100,)),
        (dense_s_pop, "X", dense_s_pop.vars, (10 * 100,)),
        (set_time_wu_dense, "V", set_time_wu_dense.vars, (10 * 100,)),
        (sparse_s_pop, "X", sparse_s_pop.vars, (10 * 10,)),
        (set_time_wu_sparse, "V", set_time_wu_sparse.vars, (10 * 10,)),
        (kernel_s_pop, "X", kernel_s_pop.vars, (3 * 3,)),
        (set_time_wu_kernel, "V", set_time_wu_kernel.vars, (3 * 3,)),
        (dense_cu, "X", dense_cu.vars, (10 * 100,)),
        (set_time_cu_dense, "V", set_time_cu_dense.vars, (10 * 100,)),
        (sparse_cu, "X", sparse_cu.vars, (10 * 10,)),
        (set_time_cu_sparse, "V", set_time_cu_sparse.vars, (10 * 10,))]
    while model.timestep < 20:
        # Every 10 timesteps, trigger custom update
        if (model.timestep % 10) == 0:
            model.custom_update("Test")
        model.step_time()

        # Loop through populations
        correct = 10 * ((model.timestep - 1) // 10)
        for pop, var_name, vars, shape in samples:
            # Pull variable from device
            pop.pull_var_from_device(var_name)
            
            # If shape of view doesn't match, give error
            view = vars[var_name].view
            if view.shape != shape:
                assert False, f"{pop.name} var {var_name} has wrong shape ({view.shape} rather than {shape})"
            # If values don't match, give error
            elif not np.all(np.isclose(view, correct)):
                assert False, f"{pop.name} var {var_name} has wrong value ({view} rather than {correct})"

@pytest.mark.parametrize("backend", ["single_threaded_cpu", "cuda"])
@pytest.mark.parametrize("precision", [types.Double, types.Float])
def test_custom_update_transpose(backend, precision):
    model = GeNNModel(precision, "test_custom_update_transpose", backend=backend)
    model.dt = 1.0
    
    # Create pre and postsynaptic populations
    pre_n_pop = model.add_neuron_population("PreNeurons", 100, "SpikeSource", {}, {}); 
    post_n_pop = model.add_neuron_population("PostNeurons", 100, "SpikeSource", {}, {}); 
    
    # Create forward and transpose synapse populations between populations
    forward_s_pop = model.add_synapse_population(
        "ForwardSynapses", "DENSE", 0,
        pre_n_pop, post_n_pop,
        "StaticPulse", {}, {"g": init_var("Normal", {"mean": 0.0, "sd": 1.0})}, {}, {},
        "DeltaCurr", {}, {})
    transpose_s_pop = model.add_synapse_population(
        "TransposeSynapses", "DENSE", 0,
        post_n_pop, pre_n_pop,
        "StaticPulse", {}, {"g": 0.0}, {}, {},
        "DeltaCurr", {}, {})
    
    # Create custom update to calculate transpose
    transpose_cu = model.add_custom_update(
        "Transpose", "Transpose", "Transpose",
        {}, {}, {"variable": create_wu_var_ref(forward_s_pop, "g", transpose_s_pop, "g")})
    
    # Build model and load
    model.build()
    model.load()
    
    # Run custom update to calculate transpose
    model.custom_update("Transpose")
    
    # Pull forward and transpose weights from device
    forward_s_pop.pull_var_from_device("g")
    transpose_s_pop.pull_var_from_device("g")
    
    # Reshape matrices to square and check transpose
    forward_g = np.reshape(forward_s_pop.vars["g"].view, (100, 100))
    transpose_g = np.reshape(transpose_s_pop.vars["g"].view, (100, 100))
    assert np.allclose(forward_g, np.transpose(transpose_g))

@pytest.mark.parametrize("backend", ["cuda"])
@pytest.mark.parametrize("precision", [types.Double, types.Float])
def test_custom_update_transpose_batch(backend, precision):
    model = GeNNModel(precision, "test_custom_update_transpose_batch", backend=backend)
    model.dt = 1.0
    model.batch_size = 5

    # Create pre and postsynaptic populations
    pre_n_pop = model.add_neuron_population("PreNeurons", 100, "SpikeSource", {}, {}); 
    post_n_pop = model.add_neuron_population("PostNeurons", 100, "SpikeSource", {}, {}); 
    
    # Create forward and transpose synapse populations between populations
    g = np.random.normal(size=(5, 100 * 100))
    forward_s_pop = model.add_synapse_population(
        "ForwardSynapses", "DENSE", 0,
        pre_n_pop, post_n_pop,
        static_pulse_duplicate_model, {}, {"g": g}, {}, {},
        "DeltaCurr", {}, {})
    transpose_s_pop = model.add_synapse_population(
        "TransposeSynapses", "DENSE", 0,
        post_n_pop, pre_n_pop,
        static_pulse_duplicate_model, {}, {"g": 0.0}, {}, {},
        "DeltaCurr", {}, {})
    
    # Create custom update to calculate transpose
    transpose_cu = model.add_custom_update(
        "Transpose", "Transpose", "Transpose",
        {}, {}, {"variable": create_wu_var_ref(forward_s_pop, "g", transpose_s_pop, "g")})
    
    # Build model and load
    model.build()
    model.load()
    
    # Run custom update to calculate transpose
    model.custom_update("Transpose")
    
    # Pull forward and transpose weights from device
    forward_s_pop.pull_var_from_device("g")
    transpose_s_pop.pull_var_from_device("g")
    
    # Reshape matrices to square and check transpose
    forward_g = np.reshape(forward_s_pop.vars["g"].view, (5, 100, 100))
    transpose_g = np.reshape(transpose_s_pop.vars["g"].view, (5, 100, 100))
    assert np.allclose(forward_g, np.transpose(transpose_g, axes=(0, 2, 1)))

@pytest.mark.parametrize("backend", ["cuda", "single_threaded_cpu"])
@pytest.mark.parametrize("precision", [types.Double, types.Float])
def test_custom_update_neuron_reduce(backend, precision):
    model = GeNNModel(precision, "test_custom_neuron_reduce", backend=backend)
    model.dt = 1.0
    
    # Create a neuron model with two state variables
    n_pop = model.add_neuron_population("Neurons", 50, reduction_neuron_model, 
                                        {}, {"X": init_var("Uniform", {"min": 0.0, "max": 100.0}), "Y": 0.0})

    # Create softmax custom update
    softmax_1_cu = model.add_custom_update("Softmax1", "Softmax1", softmax_1_custom_update_model,
                                           {}, {"MaxX": 0.0}, {"X": create_var_ref(n_pop, "X")})
    softmax_2_cu = model.add_custom_update("Softmax2", "Softmax2", softmax_2_custom_update_model,
                                           {}, {"SumExpX": 0.0}, {"X": create_var_ref(n_pop, "X"),
                                                                  "MaxX": create_var_ref(softmax_1_cu, "MaxX")})
    softmax_3_cu = model.add_custom_update("Softmax3", "Softmax3", softmax_3_custom_update_model,
                                           {}, {}, {"X": create_var_ref(n_pop, "X"),
                                                    "MaxX": create_var_ref(softmax_1_cu, "MaxX"),
                                                    "SumExpX": create_var_ref(softmax_2_cu, "SumExpX"),
                                                    "Y": create_var_ref(n_pop, "Y")})

    # Build model and load
    model.build()
    model.load()

    # Launch sequence of softmax update
    model.custom_update("Softmax1")
    model.custom_update("Softmax2")
    model.custom_update("Softmax3")

    # Download X and Y 
    n_pop.pull_var_from_device("X")
    n_pop.pull_var_from_device("Y")

    # Compare Y to softmax calculated with SciPy
    assert np.allclose(softmax(n_pop.vars["X"].view), 
                       n_pop.vars["Y"].view)


@pytest.mark.parametrize("backend", ["cuda"])
@pytest.mark.parametrize("precision", [types.Double, types.Float])
def test_custom_update_neuron_reduce_batch(backend, precision):
    model = GeNNModel(precision, "test_custom_neuron_reduce_batch", backend=backend)
    model.dt = 1.0
    model.batch_size = 5
    
    # Create a neuron model with two state variables
    x = np.random.uniform(high=100.0, size=(5, 50))
    n_pop = model.add_neuron_population("Neurons", 50, reduction_neuron_model, {}, {"X": x, "Y": 0.0})

    # Create softmax custom update
    softmax_1_cu = model.add_custom_update("Softmax1", "Softmax1", softmax_1_custom_update_model,
                                           {}, {"MaxX": 0.0}, {"X": create_var_ref(n_pop, "X")})
    softmax_2_cu = model.add_custom_update("Softmax2", "Softmax2", softmax_2_custom_update_model,
                                           {}, {"SumExpX": 0.0}, {"X": create_var_ref(n_pop, "X"),
                                                                  "MaxX": create_var_ref(softmax_1_cu, "MaxX")})
    softmax_3_cu = model.add_custom_update("Softmax3", "Softmax3", softmax_3_custom_update_model,
                                           {}, {}, {"X": create_var_ref(n_pop, "X"),
                                                    "MaxX": create_var_ref(softmax_1_cu, "MaxX"),
                                                    "SumExpX": create_var_ref(softmax_2_cu, "SumExpX"),
                                                    "Y": create_var_ref(n_pop, "Y")})

    # Build model and load
    model.build()
    model.load()

    # Launch sequence of softmax update
    model.custom_update("Softmax1")
    model.custom_update("Softmax2")
    model.custom_update("Softmax3")

    # Download X and Y 
    n_pop.pull_var_from_device("Y")

    # Compare Y to softmax calculated with SciPy
    assert np.allclose(softmax(x, axis=1), 
                       n_pop.vars["Y"].view)

@pytest.mark.parametrize("backend", ["cuda"])
@pytest.mark.parametrize("precision", [types.Double, types.Float])
def test_custom_update_batch(backend, precision):
    pass


if __name__ == '__main__':
    test_custom_update_transpose_batch("cuda", types.Float)
