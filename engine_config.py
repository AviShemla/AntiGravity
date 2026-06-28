import os
import pymc as pm

def configure_bayesian_engine():
    """
    Universally enforces high-speed PyTensor compilation and standardizes the Rust-based sampler.
    This must be imported BEFORE any PyMC models are instantiated.
    """
    # Force PyTensor to use fast_compile across the entire OS environment
    os.environ["PYTENSOR_FLAGS"] = "cxx=,optimizer=fast_compile"
    
    # Return the standardized config dictionary for pm.sample()
    sampler_config = {
        "draws": 1000,
        "tune": 1000,
        "chains": 1,
        "target_accept": 0.85,
        "random_seed": 42,
        "progressbar": False,
        "nuts_sampler": "pymc"
    }
    
    return sampler_config

def configure_sv_engine():
    """
    Returns the distinct sampling configuration for the Stochastic Volatility sub-engine.
    """
    sv_config = {
        "draws": 1000,
        "tune": 1000,
        "chains": 1,
        "cores": 1,
        "progressbar": False,
        "nuts_sampler": "pymc"
    }
    return sv_config
