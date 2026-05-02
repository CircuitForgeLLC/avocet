"""Backward-compat shim -- logic moved to app/data/corrections.py."""
from app.data.corrections import (  # noqa: F401
    router,
    set_data_dir as set_sft_data_dir,
    set_config_dir as set_sft_config_dir,
    set_default_bench_results_dir,
    _DEFAULT_BENCH_RESULTS_DIR,
)
