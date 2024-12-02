import robotic as ry
import numpy as np

from abc import ABC, abstractmethod

from typing import List
from numpy.typing import NDArray

from configuration import Configuration, config_dist

# from dependency_graph import DependencyGraph


class Goal(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def satisfies_constraints(self, q: NDArray, tolerance:float):
        pass

    @abstractmethod
    def sample(self):
        pass


# class DummyGoal(ABC):
#     def __init__(self):
#         pass

#     def satisfies_constraints(self, q, tolerance):
#         return True

#     def sample(self):
#         pass


class GoalRegion(Goal):
    def __init__(self, limits: NDArray):
        self.limits = limits

    def satisfies_constraints(self, q: NDArray, _):
        if np.all(q > self.limits[0, :]) and np.all(q < self.limits[1, :]):
            return True

    def sample(self):
        q = (
            np.random.rand(len(self.limits[0, :]))
            * (self.limits[1, :] - self.limits[0, :])
            + self.limits[0, :]
        )
        return q


# TODO: implement sampler to sample a goal
class ConstrainedGoal(Goal):
    pass


class GoalSet(Goal):
    def __init__(self, goals):
        self.goals = goals

    def satisfies_constraints(self, q: NDArray, tolerance: float) -> bool:
        for g in self.goals:
            if np.linalg.norm(g - q) < tolerance:
                return True

        return False

    def sample(self) -> NDArray:
        rnd = np.random.randint(0, len(self.goals))
        return self.goals[rnd]


class SingleGoal(Goal):
    def __init__(self, goal: NDArray):
        self.goal = goal

    def satisfies_constraints(self, q: ry.Config, tolerance: float) -> bool:
        if np.linalg.norm(self.goal - q) < tolerance:
            return True

        return False

    def sample(self) -> NDArray:
        return self.goal


class Task:
    name: str
    robots: List[str]
    goal: Goal

    # things for manipulation
    type: str
    frames: List[str]
    side_effect: str

    # things for the future:
    constraints = List

    def __init__(self, robots, goal, type=None, frames=None, side_effect=None):
        self.robots = robots
        self.goal = goal

        # constraints
        self.type = type
        self.frames = frames
        self.side_effect = side_effect


class State:
    q: Configuration
    m: List[int]

    def __init__(self, q, m):
        self.q = q
        self.mode = m


def state_dist(start: State, end: State) -> float:
    if start.mode != end.mode:
        return np.inf

    return config_dist(start.q, end.q)

# TODO: split into env + problem specification
class base_env(ABC):
    def __init__(self):
        pass

    def get_robot_dim(self, robot: str):
        return self.robot_dims[robot]

    def get_start_pos(self):
        return self.start_pos

    def get_start_mode(self):
        return self.start_mode

    def get_sequence(self):
        return self.sequence

    def get_robot_sequence(self, robot: str):
        pass

    def set_to_mode(self, mode: List[int]):
        pass

    def get_all_bounds(self):
        self.bounds

    # def get_robot_bounds(self):
    #     self.bounds

    # @abstractmethod
    # def get_single_robot_env(self, robot):
    #     pass

    @abstractmethod
    def show_config(self, q):
        pass

    @abstractmethod
    def show(self):
        pass

    @abstractmethod
    def done(self, q: Configuration, mode: List[int]):
        pass

    @abstractmethod
    def get_next_mode(self, q: Configuration, mode: List[int]):
        pass

    @abstractmethod
    def is_collision_free(self, q: Configuration, mode: List[int]):
        pass

    @abstractmethod
    def is_edge_collision_free(
        self,
        q1: Configuration,
        q2: Configuration,
        mode: List[int],
        resolution: float = 0.1,
    ):
        pass

    @abstractmethod
    def is_path_collision_free(self, path: List[State]):
        pass

    def is_valid_plan(self, path: List[State]):
        # check if it is collision free and if all modes are passed in order
        # only take the configuration into account for that
        mode = self.start_mode
        for i in range(len(path)):
            # check if the state is collision free
            if not self.is_collision_free(path[i].q.state(), mode):
                print(f"There is a collision at index {i}")
                # col = self.C.getCollisionsTotalPenetration()
                # print(col)
                self.show()
                return False

            # if the next mode is a transition, check where to go
            if self.is_transition(path[i].q, mode):
                # TODO: this does not work if multiple switches are possible at the same time
                next_mode = self.get_next_mode(path[i].q, mode)

                if path[i + 1].mode == next_mode:
                    mode = next_mode

        if not self.done(path[-1].q, path[-1].mode):
            print("Final mode not reached")
            return False

        return True

    @abstractmethod
    def config_cost(self, start: Configuration, goal: Configuration):
        pass

    @abstractmethod
    def batch_config_cost(
        self,
        starts: List[Configuration],
        ends: List[Configuration],
    ):
        pass

    def state_cost(self, start: State, end: State) -> float:
        if start.mode != end.mode:
            return np.inf

        return self.cost(start.q, end.q)
