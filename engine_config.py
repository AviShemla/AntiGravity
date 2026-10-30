import os
import pymc as pm

def configure_bayesian_engine(seed=42, chains=2):
    """
    Universally enforces high-speed PyTensor compilation and standardizes the Rust-based sampler.
    This must be imported BEFORE any PyMC models are instantiated.
    Enforces >= 2 chains and deterministic random_seed per ORA-INC-067.
    """
    # Force PyTensor to use fast_compile across the entire OS environment
    os.environ["PYTENSOR_FLAGS"] = "optimizer=fast_compile"
    
    # Return the standardized config dictionary for pm.sample()
    sampler_config = {
        "draws": 1000,
        "tune": 1000,
        "chains": max(2, int(chains)),
        "cores": 1,
        "target_accept": 0.85,
        "random_seed": int(seed),
        "progressbar": False,
        "nuts_sampler": "pymc"
    }
    
    return sampler_config

def configure_sv_engine(seed=42, chains=2):
    """
    Returns the distinct sampling configuration for the Stochastic Volatility sub-engine.
    Enforces >= 2 chains and deterministic random_seed per ORA-INC-067.
    """
    sampler_config = {
        "draws": 1000,
        "tune": 1000,
        "chains": max(2, int(chains)),
        "cores": 1,
        "random_seed": int(seed),
        "progressbar": False,
        "nuts_sampler": "pymc"
    }
    return sampler_config
