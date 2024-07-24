# -*- coding: utf-8 -*-
"""Agent_class__gSDE.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/github/Gaianeve/The_real_Fufi/blob/main/Software/Agent_class__gSDE.ipynb

# Agent class 🤖
Defining the the actor-critic NN structure.
"""

# importing libraries
import os
import numpy as np
import torch
import torch.nn as nn
from torch.distributions.categorical import Categorical
from torchsummary import summary
import gym
from datetime import datetime

from gsde_class import gSDE

#getting cute unique name for checkpoint
def get_checkpoint_name(epoch_v):
  now = datetime.now()
  today = now.strftime("%Y_%m_%d_%H_%M_%S")
  check_name = 'checkpoint' + '_' + str(epoch_v) + '_' + today
  return check_name

"""## PPO structure 🦄 ✨
Defining the basic layer for PPO
"""

# init layer
def layer_init(layer, std=np.sqrt(2), bias_const=0.0):
  torch.nn.init.orthogonal_(layer.weight, std)
  torch.nn.init.constant_(layer.bias, bias_const)
  return layer

"""## Here's the actual agent 🐶 🦾
🪄 Differences from the previous versions:
* Added gSDE:
Mostly taken from stablebaseline implementation [here](https://github.com/DLR-RM/stable-baselines3/blob/master/stable_baselines3/common/distributions.py), called
```
StateDependentNoiseDistribution
```
Paper [here](https://arxiv.org/abs/2005.05719)

* PPO for a continous action space. The code is that of the CleanRL implementation [here](https://github.com/vwxyzjn/cleanrl/blob/master/cleanrl/ppo_continuous_action.py).

"""

# agent class
class Agent(nn.Module):
  def __init__(self, envs, use_sde):
      super().__init__()
      #assign environment to interact with
      self.envs = envs
      #gSDE flag
      self.use_sde = use_sde
        
      #actor critic NN
      self.critic = nn.Sequential(
          layer_init(nn.Linear(np.array(envs.single_observation_space.shape).prod(), 64)),
          nn.Tanh(),
          layer_init(nn.Linear(64, 64)),
          nn.Tanh(),
          layer_init(nn.Linear(64, 1), std=1.0),
      )
      self.actor_mean = nn.Sequential(
          layer_init(nn.Linear(np.array(envs.single_observation_space.shape).prod(), 64)),
          nn.Tanh(),
          layer_init(nn.Linear(64, 64)),
          nn.Tanh(),
          layer_init(nn.Linear(64, np.prod(envs.single_action_space.shape)), std=0.01),
      )
      self.actor_logstd = nn.Parameter(torch.zeros(1, np.prod(envs.single_action_space.shape)))
      #learn log of standard dev
      
  ## keep in mind that x are the observations
  def get_value(self, x):
      return self.critic(x)

  def get_action_and_value(self, x, action=None):
      action_mean = self.actor_mean(x)
      action_logstd = self.actor_logstd.expand_as(action_mean) #match dimention of action mean
      action_std = torch.exp(action_logstd)
        
      if self.use_sde:
        #sample from SDE distribution
        action_dim = np.prod(self.envs.single_action_space.shape)
        observation_dim = np.prod(self.envs.single_action_space.shape)
        probs = gSDE(action_dim = action_dim,latent_sde_dim = observation_dim, mean_actions = action_mean, log_std = action_std, latent_sde = x)
      else:
        #sample from standard gaussian
        probs = Normal(action_mean, action_std)

      if action is None:
          action = probs.sample()
      return action, probs.log_prob(action).sum(1), probs.entropy().sum(1), self.critic(x)

    # NN summary
  def print_summary(self, envs):
    print('Actor summary')
    print(summary(self.actor, envs.single_observation_space.shape))
    print('Critic summary')
    print(summary(self.critic, envs.single_observation_space.shape))

  def get_parameters(self):
    #useful if wanting to check the updating of NN parameters
    for name, param in self.named_parameters():
      print(name, param.data)

  # checkpoints
  def save_checkpoint(self, epoch_v):
    checkpoint_name = get_checkpoint_name(epoch_v)
    directory = os.getcwd() + '/' + 'checkpoints/'
    #if it doesn't exists, then create it
    if not os.path.exists(directory):
      os.mkdir(directory)
      print('Dear human, checkpoint directory did not existed. I created it for you ')
    path = directory + checkpoint_name
    print("=> saving checkpoint '{}'".format(path))
    torch.save(self, path)

  def resume_from_checkpoint(self, path):
    print("=> loading checkpoint '{}'".format(path))
    return torch.load(path)

  def save_agent(self, file_name):
    directory = os.getcwd() + '/' + 'models/'
    #if it doesn't exists, then create it
    if not os.path.exists(directory):
      os.mkdir(directory)
      print('Dear human, saved model directory did not existed. I created it for you ')
    path = directory + file_name
    print("=> saving model as best agent in '{}'".format(path))
    torch.save(self, path)

  def load_agent(self,path):
     print("=> loading model from '{}'".format(path))
     return torch.load(path)



