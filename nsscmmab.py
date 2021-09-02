# -*- coding: utf-8 -*-
# =============================================
# Title:  Piece-wise Stationary SCM-MAB
# File:   nsscmmab.py
# Date:   10 July 2021
# =============================================


# import sys

# sys.path.append("..")
# sys.path.append("../src")
# sys.path.append("../../npsem")

from networkx.classes import MultiDiGraph
from numpy import vectorize
from tqdm import trange

from npsem.bandits import play_bandits
from npsem.model import StructuralCausalModel, default_P_U
from npsem.scm_bandits import SCM_to_bandit_machine, arm_types, arms_of
from npsem.utils import subseq
from src.examples.example_setup import setup_DynamicIVCD
from src.utils.dag_utils.graph_functions import get_time_slice_sub_graphs, make_time_slice_causal_diagrams


class NSSCMMAB:
    """
    Assumptions:
    - Data is generated by a non-stationary process
    - We do not have access to the SEM so we need to estimate it
    - Assume that the model is piece-wise stationary
    """

    def __init__(
        self,
        G: MultiDiGraph,  #  A dynamic Bayesian network
        SEM: classmethod,
        mu1: dict,  # Reward distribution
        node_info: dict,  # Has to contain a domain key per manipulative variable
        confounder_info: dict,
        base_target_variable: str,
        horizon: int,
        n_trials: int,
        n_jobs: int,
        arm_strategy: str = "POMIS",
        bandit_algorithm: str = "TS",  # Assumes that within time-slice bandit is stationary
    ):

        self.T = max([int(s) for s in "".join(G.nodes) if s.isdigit()]) + 1
        # Extract all target variables from the causal graphical model
        self.all_target_variables = list(filter(lambda k: base_target_variable in k, G.nodes))
        sub_DAGs = get_time_slice_sub_graphs(G, self.T)
        # Causal diagrams used for making SCMs upon which bandit algo acts
        self.causal_diagrams = make_time_slice_causal_diagrams(sub_DAGs, node_info, confounder_info)
        sem = SEM()  #  Does not change throuhgout
        self.static_sem = sem.static()
        self.dynamic_sem = sem.dynamic()
        self.P_U = default_P_U(mu1)
        self.domains = {key: val["domain"] for key, val in node_info.items()}
        # Remains the same for all time-slices (just background variables)
        self.more_U = {key for key in node_info.keys() if key[0] == "U"}

        self.SCMs = {t: None for t in range(self.T)}

        # TODO: prior for all edges in DBN

        assert arm_strategy in arm_types()
        self.arm_strategy = arm_strategy
        assert bandit_algorithm in ["TS", "UCB"]
        self.play_bandit_args = {"T": horizon, "algo": bandit_algorithm, "n_trials": n_trials, "n_jobs": n_jobs}

    # Play piece-wise stationary bandit
    def run(self):

        # Walk through the graph, from left to right, i.e. the temporal dimension
        for temporal_index in trange(self.T, desc="Time index"):

            # Get target for this time index
            target = self.all_target_variables[temporal_index]
            # Check that indices line up for this time-slice
            target_var_only, target_var_temporal_index = target.split("_")
            assert int(target_var_temporal_index) == temporal_index

            # Create SCM
            # TODO: CD must take into account the optimal actions selected at t-1 if t > 0 OR?
            self.SCMs[temporal_index] = StructuralCausalModel(
                temporal_index=temporal_index,
                G=self.causal_diagrams[temporal_index],
                F=self.static_sem if temporal_index == 0 else self.dynamic_sem(clamped=optimal_node_setting),
                P_U=self.P_U,
                D=self.domains,
                more_U=self.more_U,
            )

            #  Convert time-slice SCM to bandit machine
            mu, arm_setting = SCM_to_bandit_machine(self.SCMs[temporal_index], target_variable=target_var_only)
            #  Select arm strategy, one of: "POMIS", "MIS", "Brute-force", "All-at-once"
            arm_selected = arms_of(self.arm_strategy, arm_setting, self.SCMs[temporal_index].G, target)
            arm_corrector = vectorize(lambda x: arm_selected[x])

            # Set the rewards distribution
            self.play_bandit_args["mu"] = subseq(mu, arm_selected)
            # Pick action/intervention by playing MAB
            arm_played, rewards = play_bandits(**self.play_bandit_args)
            to_something_with_this_variable = arm_corrector(arm_played)

            # TODO: investigate rewards and figure out which intervention is the best

            # TODO: what do we do with un-played arms (i.e. nodes) --  are they fixed too?

            # Clamp nodes corresponding to the best intervention
            optimal_node_setting = {v: val for v, val in zip(self.causal_diagrams[temporal_index].V, arm_played)}
            # Don't assign the wrong stuff (non-boolean)
            assert all(val == 0 or val == 1 for val in optimal_node_setting.values())

            # TODO: need to update statistics for next time-step through the transition functions (though this probably already happens in SCM_to_bandit_machine)

            # TODO: need to fix params in the SEM based on choices for this MAB


def main():
    """
    Test method with standard params.
    """
    params = setup_DynamicIVCD()
    m = NSSCMMAB(**params)
    m.run()


if __name__ == "__main__":
    # TODO: write tests
    main()
