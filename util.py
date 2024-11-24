import numpy as np
from numpy.typing import NDArray
from planning_env import *
from rai_envs import *

from typing import List

# TODO:
# add cost/distance to the envs

def state_dist(start: State, end: State) -> float:
    if start.mode != end.mode:
        return np.inf

    return config_dist(start.q, end.q)


def state_cost(start: State, end: State) -> float:
    if start.mode != end.mode:
        return np.inf

    return config_cost(start.q, end.q)


def path_cost(path: List[State]) -> float:
    cost = 0

    batch_costs = batch_config_cost(path[:-1], path[1:])
    return np.sum(batch_costs)
    # print("A")
    # print(batch_costs)

    # costs = []

    for i in range(len(path) - 1):
        # costs.append(float(config_cost(path[i].q, path[i + 1].q)))
        cost += config_cost(path[i].q, path[i + 1].q)

    # print(costs)

    return cost