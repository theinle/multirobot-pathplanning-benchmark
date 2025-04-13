import robotic as ry
import numpy as np
import random
import time

from typing import List, Dict, Optional
from numpy.typing import NDArray

from multi_robot_multi_goal_planning.problems.rai_config import *
from multi_robot_multi_goal_planning.problems.planning_env import (
    BaseModeLogic,
    SequenceMixin,
    UnorderedButAssignedMixin,
    State,
    Task,
    SingleGoal,
    GoalSet,
    GoalRegion,
)
from multi_robot_multi_goal_planning.problems.rai_base_env import rai_env


class rai_two_dim_env(UnorderedButAssignedMixin, rai_env):
    def __init__(self, agents_can_rotate=True):
        self.C = make_2d_rai_env_no_obs(agents_can_rotate=agents_can_rotate)
        # self.C.view(True)

        self.robots = ["a1", "a2"]

        rai_env.__init__(self)

        # r1 starts at both negative
        r1_state = self.C.getJointState()[self.robot_idx["a1"]]
        # r2 starts at both positive
        r2_state = self.C.getJointState()[self.robot_idx["a2"]]

        r1_goal = r1_state * 1.0
        r1_goal[:2] = [-0.5, 0.5]

        r2_goal_1 = r2_state * 1.0
        r2_goal_1[:2] = [0.5, -0.5]
        r2_goal_2 = r2_state * 1.0
        r2_goal_2[:2] = [0.5, 0.5]

        self.tasks = [
            Task(
                ["a1", "a2"],
                GoalRegion(self.C.getJointLimits()),
            ),
            # r1
            Task(["a1"], SingleGoal(r1_goal)),
            # r2
            Task(["a2"], SingleGoal(r2_goal_1)),
            Task(["a2"], SingleGoal(r2_goal_2)),
            Task(["a2"], SingleGoal(r2_goal_1)),
            Task(["a2"], SingleGoal(r2_goal_2)),
            # terminal mode
            Task(
                ["a1", "a2"],
                SingleGoal(self.C.getJointState()),
            ),
        ]

        self.tasks[0].name = "dummy_start"
        self.tasks[1].name = "a1_goal"
        self.tasks[2].name = "a2_goal_0"
        self.tasks[3].name = "a2_goal_1"
        self.tasks[4].name = "a2_goal_2"
        self.tasks[5].name = "a2_goal_3"
        self.tasks[6].name = "terminal"

        self.per_robot_tasks = [[1], [2, 3, 4, 5]]
        self.terminal_task = 6

        self.collision_tolerance = 0.01

        BaseModeLogic.__init__(self)


class rai_two_dim_square_env(UnorderedButAssignedMixin, rai_env):
    def __init__(self, agents_can_rotate=True):
        self.C = make_2d_rai_env_no_obs(agents_can_rotate=agents_can_rotate)
        # self.C.view(True)

        self.robots = ["a1", "a2"]

        rai_env.__init__(self)

        # r1 starts at both negative (-.5, -.5)
        r1_state = self.C.getJointState()[self.robot_idx["a1"]]
        # r2 starts at both positive (.5, .5)
        r2_state = self.C.getJointState()[self.robot_idx["a2"]]

        r1_goal = r1_state * 1.0
        r1_goal[:2] = [-0.5, 0.5]

        r2_goal_1 = r2_state * 1.0
        r2_goal_1[:2] = [0.5, -0.5]
        r2_goal_2 = r2_state * 1.0
        r2_goal_2[:2] = [-0.5, -0.5]
        r2_goal_3 = r2_state * 1.0
        r2_goal_3[:2] = [-0.5, 0.5]

        self.tasks = [
            Task(
                ["a1", "a2"],
                GoalRegion(self.C.getJointLimits()),
            ),
            # r1
            Task(["a1"], SingleGoal(r1_goal)),
            # r2
            Task(["a2"], SingleGoal(r2_goal_1)),
            Task(["a2"], SingleGoal(r2_goal_2)),
            Task(["a2"], SingleGoal(r2_goal_3)),
            # Task(["a2"], SingleGoal(r2_goal_3)),
            # terminal mode
            Task(
                ["a1", "a2"],
                SingleGoal(self.C.getJointState()),
            ),
        ]

        self.tasks[0].name = "dummy_start"
        self.tasks[1].name = "a1_goal"
        self.tasks[2].name = "a2_goal_0"
        self.tasks[3].name = "a2_goal_1"
        self.tasks[4].name = "a2_goal_2"
        self.tasks[5].name = "terminal"

        self.per_robot_tasks = [[1], [2, 3, 4]]
        self.terminal_task = 5

        self.collision_tolerance = 0.01

        BaseModeLogic.__init__(self)


class rai_two_dim_circle_env(UnorderedButAssignedMixin, rai_env):
    def __init__(self, agents_can_rotate=False):
        self.C = make_2d_rai_env_no_obs(agents_can_rotate=agents_can_rotate)
        # self.C.view(True)

        self.robots = ["a1", "a2"]

        rai_env.__init__(self)

        # r1 starts at both negative (-.5, -.5)
        r1_state = self.C.getJointState()[self.robot_idx["a1"]]
        # r2 starts at both positive (.5, .5)
        r2_state = self.C.getJointState()[self.robot_idx["a2"]]

        r1_goal = r1_state * 1.0
        r1_goal[:2] = [-0.5, 0.5]

        r2_goals = []

        N = 6
        r = 0.5

        for i in range(N):
            goal = r2_state * 1.0
            goal[:2] = [
                np.sin(1.0 * i / N * np.pi * 2) * r,
                np.cos(1.0 * i / N * np.pi * 2) * r,
            ]
            r2_goals.append(goal)

        self.tasks = [
            Task(
                ["a1", "a2"],
                GoalRegion(self.C.getJointLimits()),
            ),
            # r1
            Task(["a1"], SingleGoal(r1_goal)),
        ]

        for i, g in enumerate(r2_goals):
            self.tasks.append(
                Task(["a2"], SingleGoal(g)),
            )
            self.tasks[-1].name = f"a2_goal_{i}"

        self.tasks.append(  # terminal mode
            Task(
                ["a1", "a2"],
                SingleGoal(self.C.getJointState()),
            ),
        )
        self.tasks[-1].name = "terminal"

        self.tasks[0].name = "dummy_start"
        self.tasks[1].name = "a1_goal"

        self.per_robot_tasks = [[1], [2 + i for i in range(len(r2_goals))]]
        self.terminal_task = len(self.tasks) - 1

        self.collision_tolerance = 0.01

        BaseModeLogic.__init__(self)


class rai_two_dim_circle_single_agent(UnorderedButAssignedMixin, rai_env):
    def __init__(self, agents_can_rotate=False):
        self.C, keyframes = make_random_two_dim_single_goal(
            num_agents=1,
            num_obstacles=0,
            agents_can_rotate=agents_can_rotate,
        )
        # self.C.view(True)

        self.robots = [f"a{i}" for i in range(1)]

        rai_env.__init__(self)

        state = self.C.getJointState()[self.robot_idx["a0"]]

        goals = []

        N = 5
        r = 1.0

        for i in range(N):
            goal = state * 1.0
            goal[:2] = [
                np.sin(1.0 * i / N * np.pi * 2) * r,
                np.cos(1.0 * i / N * np.pi * 2) * r,
            ]
            goals.append(goal)

        self.tasks = [
            Task(
                ["a0"],
                GoalRegion(self.C.getJointLimits()),
            ),
        ]

        for i, g in enumerate(goals):
            self.tasks.append(
                Task(["a0"], SingleGoal(g)),
            )
            self.tasks[-1].name = f"a2_goal_{i}"

        self.tasks.append(  # terminal mode
            Task(
                ["a0"],
                SingleGoal(self.C.getJointState()),
            ),
        )
        self.tasks[-1].name = "terminal"

        self.tasks[0].name = "dummy_start"

        self.per_robot_tasks = [[1 + i for i in range(len(goals))]]
        self.terminal_task = len(self.tasks) - 1

        self.collision_tolerance = 0.01

        BaseModeLogic.__init__(self)
