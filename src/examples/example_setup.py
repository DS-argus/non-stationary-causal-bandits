from scm_mab.utils import rand_bw, seeded
from src.examples.SEMs import testSEM
from multiprocessing import cpu_count
from src.utils.dag_utils.graph_functions import make_graphical_model, make_networkx_object


def setup_DynamicIVCD(T=3):

    with seeded(seed=0):
        mu1 = {
            "U_X": rand_bw(0.01, 0.2, precision=2),
            "U_Y": rand_bw(0.01, 0.2, precision=2),
            "U_Z": rand_bw(0.01, 0.99, precision=2),
            "U_XY": rand_bw(0.4, 0.6, precision=2),
        }

        # Node properties are constant across time-slices
        #  We could use defaultdict(lambda: (0,1)) instead of specifying each domain separately

        # Endogenous
        node_info = {
            "Z": {"type": "manipulative", "domain": (0, 1)},
            "X": {"type": "manipulative", "domain": (0, 1)},
            "Y": {"type": "manipulative", "domain": (0, 1)},
        }

        # Constructor for adding [the same] unobserved confounders to graphical model
        confounders = {t: ("X", "Y") for t in range(T)}

        graph_view = make_graphical_model(
            start_time=0,
            stop_time=T - 1,
            topology="dependent",
            target_node="Y",
            node_information=node_info,
            confounder_info=confounders,
            verbose=False,
        )

        # Exogenous / background conditions
        background_info = {
            "U_Z": {"type": "background", "domain": (0, 1)},
            "U_X": {"type": "background", "domain": (0, 1)},
            "U_Y": {"type": "background", "domain": (0, 1)},
            "U_XY": {"type": "confounder", "domain": (0, 1)},
        }

        node_info = node_info | background_info

        G = make_networkx_object(graph_view, node_info, T)

        return {
            "G": G,
            "SEM": testSEM,
            "mu1": mu1,
            "node_info": node_info,
            "confounder_info": confounders,
            "base_target_variable": "Y",
            "horizon": 5000,
            "n_trials": 100,
            "n_jobs": 3 * cpu_count() // 4,
        }
