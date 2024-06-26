from copy import deepcopy
from networkx.classes import MultiDiGraph
from numpy import vectorize
from tqdm import trange

from scm_mab.bandits import play_bandits
from scm_mab.model import StructuralCausalModel, default_P_U
from scm_mab.scm_bandits import arm_types, arms_of, new_SCM_to_bandit_machine
from scm_mab.utils import subseq
from src.examples.example_setup import setup_DynamicIVCD
from src.utils.dag_utils.graph_functions import get_time_slice_sub_graphs, make_time_slice_causal_diagrams
from src.utils.postprocess import get_results
from src.utils.transitions import fit_transition_functions, get_transition_pairs
from src.utils.emissions import fit_emission_functions, get_emission_pairs


class CCB:
    def __init__(
        self,
        G: MultiDiGraph,  #  A dynamic Bayesian network
        SEM: classmethod,
        mu1: dict,
        node_info: dict,  # Has to contain a domain key per manipulative variable
        confounder_info: dict,
        base_target_variable: str,
        horizon: int,
        n_trials: int,
        n_jobs: int,
        sem_estimator: dict = None,
        observational_samples: dict = None,
        arm_strategy: str = "POMIS",
        bandit_algorithm: str = "TS",  # Assumes that within time-slice bandit is stationary
    ):

        self.T = G.total_time
        time_slice_nodes = G.time_slice_manipulative_nodes
        # Extract all target variables from the causal graphical model
        self.all_target_variables = [s for s in G.nodes if s.startswith(base_target_variable)]
        sub_DAGs = get_time_slice_sub_graphs(G, self.T)
        # Causal diagrams used for making SCMs upon which bandit algo acts
        self.causal_diagrams = make_time_slice_causal_diagrams(sub_DAGs, confounder_info)

        if observational_samples:
            # We use observed samples of the system to estimate the (discrete) structural equation model
            self.transfer_pairs = get_transition_pairs(G)
            self.emission_pairs = get_emission_pairs(G)
            self.transition_functions = fit_transition_functions(observational_samples, self.transfer_pairs)
            self.emission_functions = fit_emission_functions(observational_samples, self.emission_pairs)
            # TODO: need a sem_hat function to put it all together
            #  XXX: we can write two version of the estimation, one which uses samples from the whole graph or another which uses only the measured variables (and so does not have any idea about the background model or the confounders). This labours under two different assumptions:
            # 1. We can measure the background variables (but if we can do that, then they are not really background variables)
            # 2. We cannot measure them in which case we can only model the interaction on the manipulative and non-manipulative variables.
            self.sem = sem_estimator
        else:
            self.transition_functions = None
            # We use the true structural equation model in the absence of observational samples
            self.sem = SEM()  #  Does not change throuhgout

        self.P_U = default_P_U(mu1)
        self.mu1 = mu1
        self.domains = {key: val["domain"] for key, val in node_info.items()}
        # Remains the same for all time-slices (just background variables)
        self.more_U = {key for key in node_info.keys() if key[0] == "U"}
        self.SCMs = {t: None for t in range(self.T)}

        # Bandit settings
        assert arm_strategy in arm_types()
        self.arm_strategy = arm_strategy
        assert bandit_algorithm in ["TS", "UCB"]
        self.play_bandit_args = {"T": horizon, "algo": bandit_algorithm, "n_trials": n_trials, "n_jobs": n_jobs}

        # Results
        self.results = {t: None for t in range(self.T)}
        self.reward_distribution = deepcopy(self.results)
        self.arm_setting = deepcopy(self.results)

        # Stores the intervention, and the downstream effect of the intervention, for each time-slice
        self.blanket = {t: None for t in range(self.T)}
        self.interventions = []  #  The per-time-slice best interventions
        self.empty_slice = {V: None for V in time_slice_nodes}

    # Play piece-wise stationary SCM-MAB
    def run(self):

        # Walk through the graph, from left to right, i.e. the temporal dimension
        for temporal_index in trange(self.T, desc="Time index"):

            # Get target for this time index
            target = self.all_target_variables[temporal_index]
            # Check that indices line up for this time-slice
            target_var_only, target_var_temporal_index = target.split("_")
            assert int(target_var_temporal_index) == temporal_index

            # Create SCM
            self.SCMs[temporal_index] = StructuralCausalModel(
                G=self.causal_diagrams[temporal_index],
                F=self.sem,  # .static() if temporal_index == 0 else self.sem.dynamic(clamped=clamped_nodes),
                P_U=self.P_U,
                D=self.domains,
                more_U=self.more_U,
            )

            #  Convert time-slice SCM to bandit machine
            mu, arm_setting = new_SCM_to_bandit_machine(
                self.SCMs[temporal_index], interventions=self.interventions, reward_variable=target_var_only
            )
            #  Select arm strategy, one of: "POMIS", "MIS", "Brute-force", "All-at-once"
            arm_selected = arms_of(self.arm_strategy, arm_setting, self.SCMs[temporal_index].G, target_var_only)
            arm_corrector = vectorize(lambda x: arm_selected[x])

            # Set the rewards distribution
            self.play_bandit_args["mu"] = subseq(mu, arm_selected)
            # Pick action/intervention by playing MAB
            arm_played, rewards = play_bandits(**self.play_bandit_args)
            arm_played = arm_corrector(arm_played)

            # Post-process
            self.results[temporal_index] = get_results(arm_played, rewards, mu)
            self.reward_distribution[temporal_index] = mu
            self.arm_setting[temporal_index] = arm_setting
            #  Get index of the best arm
            best_arm_idx = max(
                self.results[temporal_index]["frequency"], key=self.results[temporal_index]["frequency"].get
            )
            # Get the corresponding intervention of that index e.g. {'Z': 0}
            best_intervention = arm_setting[best_arm_idx]
            self.interventions.append(best_intervention)

            # Contains the optimal actions and corresponding output
            # self.blanket[temporal_index] = implement_intervention(
            #     self.SCMs[temporal_index].G.causal_order(),
            #     self.SCMs[temporal_index].F.static()
            #     if temporal_index == 0
            #     else self.SCMs[temporal_index].F.dynamic(self.interventions[-1]),
            #     self.mu1,
            #     best_intervention,
            # )

            # Contains the _transferred_ (from t-1 to t) optimal actions and corresponding output, computed before passed to SEM at next time step.
            if self.transition_functions:
                pass
                raise NotImplementedError
                # clamped_nodes = deepcopy(self.empty_slice)
                # clamped_nodes = {
                #     # TODO: need to index with transfer-pairs
                #     var: self.transfer_function[temporal_index][var](val)
                #     for var, val in self.blanket[temporal_index].items()
                #     if self.blanket[temporal_index][var] is not None or var.startswith("U")
                # }
                # # TODO: add emission functions too
            # else:
            #     pass
            #     raise NotImplementedError
            #     # clamped_nodes = self.blanket[temporal_index]


def main():
    """
    Test method with standard params.
    """
    params = setup_DynamicIVCD()
    m = CCB(**params)
    m.run()


if __name__ == "__main__":
    main()
