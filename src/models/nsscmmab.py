from npsem.bandits import play_bandits
from npsem.scm_bandits import SCM_to_bandit_machine, arms_of
from numpy import vectorize
from tqdm import trange
from utils.dag_utils.graph_functions import (get_time_slice_sub_graphs,
                                             make_time_slice_causal_diagrams)


class NSSCMMAB:
    def __init__(
        self,
        G,
        node_info: dict,
        confounder_info: dict,
        base_target_variable: str,
        arm_strategy="POMIS",
        bandit_algorithm="TS",
    ):

        T = max([int(s) for s in "".join(G.nodes) if s.isdigit()]) + 1
        # Extract all target variables from the causal graphical model
        self.all_target_variables = list(filter(lambda k: base_target_variable in k, G.nodes))
        sub_DAGs = get_time_slice_sub_graphs(G, T)
        self.causal_diagrams = make_time_slice_causal_diagrams(sub_DAGs, node_info, confounder_info)
        self.SCMs =

        # TODO: need to make container for SCMs
        # TODO: prior for all edges in DBN

        self.arm_strategy = arm_strategy
        self.bandit_algorithm = bandit_algorithm

    def run(self):

        # Walk through the graph, from left to right, i.e. the temporal dimension
        for temporal_index in trange(self.total_timesteps, desc="Time index"):

            # Get target for this time index
            target = self.all_target_variables[temporal_index]

            # Check that indices line up for this time-slice
            _, target_temporal_index = target.split("_")
            assert int(target_temporal_index) == temporal_index

            # Play this, piece-wise stationary bandit
            mu, arm_setting = SCM_to_bandit_machine(self.SCMs[temporal_index])
            arm_selected = arms_of(self.arm_strategy, arm_setting, M.G, target)
            arm_corrector = vectorize(lambda x: arm_selected[x])

            # Pick action by playing MAB
            arm_played, rewards = play_bandits(horizon, subseq(mu, arm_selected), bandit_algo, num_trial, n_jobs)

            # TODO: need to update statistics for next time-step through the transition functions
