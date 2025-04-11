import pytest

import numpy as np

from multi_robot_multi_goal_planning.problems.planning_env import (
    generate_binary_search_indices,
)
from multi_robot_multi_goal_planning.problems import get_env_by_name
from multi_robot_multi_goal_planning.problems.configuration import NpConfiguration
from multi_robot_multi_goal_planning.problems.planning_env import (
    State,
    UnorderedButAssignedMixin,
    SingleGoal,
    GoalRegion,
    Task,
    BaseModeLogic,
    Mode,
)

from multi_robot_multi_goal_planning.planners.joint_prm_planner import joint_prm_planner
from multi_robot_multi_goal_planning.planners.planner_rrtstar import RRTstar
from multi_robot_multi_goal_planning.planners.planner_birrtstar import (
    BidirectionalRRTstar,
)

from multi_robot_multi_goal_planning.planners.termination_conditions import (
    RuntimeTerminationCondition,
)


@pytest.mark.parametrize(
    "n, expected",
    [
        (1, (0,)),
        (2, (0, 1)),
        (3, (1, 0, 2)),
        (4, (1, 0, 2, 3)),
        (5, (2, 0, 3, 1, 4)),
    ],
)
def test_binary_indices(n, expected):
    assert generate_binary_search_indices(n) == expected


def test_edge_checking():
    env = get_env_by_name("abstract_test")

    q1 = NpConfiguration(np.array([-1, 0, 1, 1]), env.start_pos.array_slice)
    q2 = NpConfiguration(np.array([-1, 1, 1, 0]), env.start_pos.array_slice)

    is_collision_free = env.is_edge_collision_free(q1, q2, env.start_mode)

    assert is_collision_free


def test_edge_checking_resolution(mocker):
    env = get_env_by_name("abstract_test")

    q1 = NpConfiguration(np.array([-1, 0, 1, 1]), env.start_pos.array_slice)
    q2 = NpConfiguration(np.array([-1, 1, 1, 0]), env.start_pos.array_slice)

    mock = mocker.patch.object(env, "is_collision_free", return_value=True)

    env.is_edge_collision_free(
        q1, q2, env.start_mode, resolution=0.5, include_endpoints=True
    )
    assert mock.call_count == 3

    mock.reset_mock()
    env.is_edge_collision_free(
        q1, q2, env.start_mode, resolution=0.5, include_endpoints=False
    )
    assert mock.call_count == 1

    mock.reset_mock()
    env.is_edge_collision_free(
        q1, q2, env.start_mode, resolution=0.1, include_endpoints=False
    )
    assert mock.call_count == 9

    mock.reset_mock()
    env.is_edge_collision_free(
        q1, q2, env.start_mode, resolution=0.1, include_endpoints=True
    )
    assert mock.call_count == 11


def test_path_collision_checking(mocker):
    env = get_env_by_name("abstract_test")

    q1 = NpConfiguration(np.array([-1, 0, 1, 1]), env.start_pos.array_slice)
    q2 = NpConfiguration(np.array([-1, 1, 1, 0]), env.start_pos.array_slice)
    q3 = NpConfiguration(np.array([-1, 2, 1, -1]), env.start_pos.array_slice)

    s1 = State(q1, env.start_mode)
    s2 = State(q2, env.start_mode)
    s3 = State(q3, env.start_mode)

    is_collision_free = env.is_path_collision_free([s1, s2, s3], resolution=0.5)
    assert is_collision_free

    mock = mocker.patch.object(env, "is_collision_free", return_value=True)

    env.is_path_collision_free([s1, s2, s3], resolution=0.5, check_edges_in_order=True)
    assert mock.call_count == 5

    mock.reset_mock()
    env.is_path_collision_free([s1, s2, s3], resolution=0.5)
    assert mock.call_count == 5

    mock.reset_mock()
    env.is_path_collision_free([s1, s2, s3], resolution=0.1, check_edges_in_order=True)
    assert mock.call_count == 21

    mock.reset_mock()
    env.is_path_collision_free([s1, s2, s3], resolution=0.1)
    assert mock.call_count == 21


@pytest.mark.parametrize(
    "planner_fn",
    [
        lambda env, ptc: joint_prm_planner(env, ptc=ptc, optimize=False),
        lambda env, ptc: RRTstar(env, ptc=ptc).Plan(False),
        lambda env, ptc: BidirectionalRRTstar(env, ptc=ptc).Plan(False),
    ],
)
def test_planner_on_abstract_env(planner_fn):
    env = get_env_by_name("abstract_test")
    ptc = RuntimeTerminationCondition(10)

    path, _ = planner_fn(env, ptc)

    assert path is not None

    assert np.array_equal(path[0].q.state(), env.start_pos.state())
    assert env.is_terminal_mode(path[-1].mode)
    assert env.is_valid_plan(path)


@pytest.mark.parametrize(
    "planner_fn",
    [
        lambda env, ptc: joint_prm_planner(env, ptc=ptc, optimize=False),
        lambda env, ptc: RRTstar(env, ptc=ptc).Plan(False),
        lambda env, ptc: BidirectionalRRTstar(env, ptc=ptc).Plan(False),
    ],
)
def test_planner_on_hallway_dependency_env(planner_fn):
    env = get_env_by_name("other_hallway_dep")
    ptc = RuntimeTerminationCondition(10)

    path, _ = planner_fn(env, ptc)

    assert path is not None

    assert np.array_equal(path[0].q.state(), env.start_pos.state())
    assert env.is_terminal_mode(path[-1].mode)
    assert env.is_valid_plan(path)


class DummyClass(UnorderedButAssignedMixin):
    def __init__(self):
        # r1 starts at both negative (-.5, -.5)
        r1_state = np.array([-0.5, -0.5])
        # r2 starts at both positive (.5, .5)
        r2_state = np.array([0.5, 0.5])

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
                GoalRegion(np.array([0])),
            ),
            # r1
            Task(["a1"], SingleGoal(r1_goal)),
            # r2
            Task(["a2"], SingleGoal(r2_goal_1)),
            Task(["a2"], SingleGoal(r2_goal_2)),
            Task(["a2"], SingleGoal(r2_goal_3)),
            # terminal mode
            Task(
                ["a1", "a2"],
                SingleGoal(np.array([-0.5, -0.5, 0.5, 0.5])),
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

        self.start_pos = NpConfiguration.from_list([[0.5, 0.5], [0.5, 0.5]])

        BaseModeLogic.__init__(self)


def test_unordered_mixin():
    tmp = DummyClass()

    valid_combinations = tmp.get_valid_next_task_combinations(tmp.start_mode)
    assert len(valid_combinations) == 4

    test_mode = Mode([1, 0], tmp.start_pos)
    test_mode.prev_mode = tmp.start_mode

    valid_combinations = tmp.get_valid_next_task_combinations(test_mode)
    assert len(valid_combinations) == 4

    test_mode_2 = Mode([5, 0], tmp.start_pos)
    test_mode_2.prev_mode = test_mode

    valid_combinations = tmp.get_valid_next_task_combinations(test_mode_2)
    assert len(valid_combinations) == 3

    test_mode_3 = Mode([5, 2], tmp.start_pos)
    test_mode_3.prev_mode = test_mode_2

    valid_combinations = tmp.get_valid_next_task_combinations(test_mode_3)
    assert len(valid_combinations) == 2
    assert valid_combinations == [[5, 3], [5, 4]]

    test_mode_4 = Mode([5, 3], tmp.start_pos)
    test_mode_4.prev_mode = test_mode_3

    valid_combinations = tmp.get_valid_next_task_combinations(test_mode_4)
    assert len(valid_combinations) == 1
    assert valid_combinations == [[5, 4]]

    test_mode_5 = Mode([5, 4], tmp.start_pos)
    test_mode_5.prev_mode = test_mode_4

    valid_combinations = tmp.get_valid_next_task_combinations(test_mode_5)
    assert len(valid_combinations) == 1
    assert valid_combinations == [[5, 5]]

    test_mode_6 = Mode([5, 5], tmp.start_pos)
    test_mode_6.prev_mode = test_mode_5

    valid_combinations = tmp.get_valid_next_task_combinations(test_mode_6)
    assert len(valid_combinations) == 0
