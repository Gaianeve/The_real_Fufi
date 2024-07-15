# -*- coding: utf-8 -*-
"""Environment.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/github/Gaianeve/FUFONE/blob/main/PPO/Environment.ipynb

# Environment 🦤 🌎
Create and initizialize multiple parallel environments
"""

# importing libraries
import os
import gym

from wrappers import HistoryWrapper

"""## Build the environment 🎁 🍇
Build one single environment and wrap it with an hystory wrapper **HistoryWrapper** to fix Markov assumption break and record it with **RecordEpisodeStatistics** wrapper
"""

# making the environment
def make_env(gym_id, seed, idx, capture_video, run_name):
    def thunk():
        env = gym.make(gym_id)
        env = gym.wrappers.RecordEpisodeStatistics(env)
        env = HistoryWrapper(env, 2, True)
        if capture_video:
            if idx == 0:
              #record video every ten episodes
                env = gym.wrappers.RecordVideo(env, f"videos/{run_name}", \
                                               episode_trigger = lambda x: x % 10 == 0)
        env.seed(seed)
        env.action_space.seed(seed)
        env.observation_space.seed(seed)
        return env

    return thunk

"""## Create parallel environments  🌍 🦐"""

# vectorize environment
def vectorize_env(gym_id, seed, capture_video, run_name, num_envs):
  envs = gym.vector.SyncVectorEnv(
        [make_env(gym_id, seed + i, i, capture_video, run_name) for i in range(num_envs)]
  )
  assert isinstance(envs.single_action_space, gym.spaces.Discrete), \
  "only discrete action space is supported"
  return envs

