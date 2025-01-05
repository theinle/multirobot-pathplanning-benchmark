from multi_robot_multi_goal_planning.problems import get_env_by_name
import multi_robot_multi_goal_planning.problems as problems
from multi_robot_multi_goal_planning.problems.rai_envs import rai_env

import numpy as np
import argparse
import time
import random


def visualize_modes(env: rai_env):
    env.show()

    q_home = env.start_pos

    m = env.start_mode
    while True:
        print('--------')
        print("Mode", m)

        q = []
        next_task_combos = env.get_valid_next_task_combinations(m)
        if len(next_task_combos) > 0:
            idx = random.randint(0, len(next_task_combos)-1)
            task = env.get_active_task(m, next_task_combos[idx])
        else:
            task = env.get_active_task(m, None)
        switching_robots = task.robots
        goal_sample = task.goal.sample(m)

        if task.name is not None:
            print('Active Task name:', task.name)
        print('Involved robots: ', task.robots)
        
        print('Goal state:')
        print(goal_sample)

        print("switching robots: ", switching_robots)

        for j, r in enumerate(env.robots):
            if r in switching_robots:
                # TODO: need to check all goals here
                # figure out where robot r is in the goal description
                offset = 0
                for _, task_robot in enumerate(task.robots):
                    if task_robot == r:
                        q.append(
                            goal_sample[offset : offset + env.robot_dims[task_robot]]
                        )
                        break
                    offset += env.robot_dims[task_robot]
                # q.append(goal_sample)
            else:
                q.append(q_home.robot_state(j))

        print(q)

        print(
            "Is collision free: ",
            env.is_collision_free(type(env.get_start_pos()).from_list(q).state(), m),
        )

        # colls = env.C.getCollisions()
        # for c in colls:
        #     if c[2] < 0:
        #         print(c)

        env.show()

        if env.is_terminal_mode(m):
            break

        m = env.get_next_mode(type(env.get_start_pos()).from_list(q), m)


def benchmark_collision_checking(env: rai_env, N=5000):
    start = time.time()
    for _ in range(N):
        q = []
        for i in range(len(env.robots)):
            lims = env.limits[:, env.robot_idx[env.robots[i]]]
            if lims[0, 0] < lims[1, 0]:
                qr = (
                    np.random.rand(env.robot_dims[env.robots[i]])
                    * (lims[1, :] - lims[0, :])
                    + lims[0, :]
                )
            else:
                qr = np.random.rand(env.robot_dims[env.robots[i]]) * 6 - 3
            q.append(qr)

        m = env.sample_random_mode()

        env.is_collision_free(type(env.get_start_pos()).from_list(q).state(), m)

    end = time.time()

    print(f"Took on avg. {(end-start)/N * 1000} ms for a collision check.")


if __name__ == "__main__":
    # problems.rai_envs.rai_hallway_two_dim_dependency_graph()
    # print()
    # problems.rai_envs.rai_two_dim_three_agent_env_dependency_graph()

    parser = argparse.ArgumentParser(description="Env shower")
    parser.add_argument("env_name", nargs="?", default="default", help="env to show")
    parser.add_argument(
        "--mode",
        choices=["benchmark", "show", "modes"],
        required=True,
        help="Select the mode of operation",
    )
    args = parser.parse_args()

    # check_all_modes()

    env = get_env_by_name(args.env_name)

    if args.mode == "show":
        print("Environment starting position")
        env.show()
    elif args.mode == "benchmark":
        benchmark_collision_checking(env)
    elif args.mode == "modes":
        print("Environment modes/goals")
        visualize_modes(env)
