# -*- coding: utf-8 -*-
"""gSDE_class.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/14-PmUmqjlT_F3frLO4-ootagzOeJ1EZS
"""

from typing import Any, Dict, List, Optional, Tuple, TypeVar, Union

import numpy as np
import torch as th
from gym import spaces
from torch import nn

## Needed class for gSDE 🎡
"""
The **TanhBijector** class defines a bijective transformation using the hyperbolic tangent function (tanh). This class is often used in reinforcement learning algorithms to squash the output of the policy network to ensure that the actions remain within a specific range, typically [-1,1]
"""

from stable_baselines3.common.distributions import Distribution, TanhBijector
from torch.distributions import Bernoulli, Categorical, Normal

"""# State Dependent Noise Distribution (gSDE) 🌵
🪄 Distribution class for using generalized State Dependent Exploration (gSDE).

Paper: https://arxiv.org/abs/2005.05719 🦄

It is used to create the noise exploration matrix and compute the log probability of an action with that noise.

   * :`param action_dim`: Dimension of the action space.
   * :`param full_std:` Whether to use (n_features x n_actions) parameters for the std instead of only (n_features,)
   * :`param use_expln:` Use `expln()` function instead of `exp()` to ensure a positive standard deviation (cf paper). It allows to keep variance above zero and prevent it from growing too fast. In practice, `exp()` is usually enough.
   * `:param squash_output`: Whether to squash the output using a tanh function, this ensures bounds are satisfied.
   
   * `:param learn_features`: Whether to learn features for gSDE or not. This will enable gradients to be backpropagated through the features ``latent_sde`` in the code.

   * `:param epsilon:` small value to avoid NaN due to numerical imprecision.
"""


"""## gSDE class 🐧"""

class gSDE(Distribution):
    bijector: Optional[TanhBijector]
    latent_sde_dim: Optional[int]
    weights_dist: Normal
    _latent_sde: th.Tensor
    exploration_mat: th.Tensor
    exploration_matrices: th.Tensor

    def __init__(
        self,
        action_dim: int,
        observation_dim: int
        observation: Optional[th.Tensor] = None,
        mean_actions: Optional[th.Tensor] = None,
        log_std: Optional[th.Tensor] = None,
        full_std: bool = True,
        use_expln: bool = False,
        squash_output: bool = False,
        learn_features: bool = True,
        epsilon: float = 1e-6,
    ):
        super().__init__()
        self.action_dim = action_dim
        self.obs_dim = observation_dim
        self.x = observation
        self.mean_actions = mean_actions
        self.log_std = log_std
        self.latent_sde_dim = self.mean_actions.shape
        self.use_expln = use_expln
        self.full_std = full_std
        self.epsilon = epsilon
        self.learn_features = learn_features
        self.bijector = TanhBijector(epsilon) if squash_output else None

        #get combination of action and coordinates for noise computation
        self.latent_sde = th.nn.Linear(self.obs_dim, latent_sde_dim)
        self._latent_sde = self.latent_sde(self.x)
    #-------------------------------------------- get actions ------------------------------------------------------
    def get_std(self) -> th.Tensor:
        """
        Get the standard deviation from the learned parameter
        (log of it by default). This ensures that the std is positive.

        :param log_std:
        :return:
        """
        if self.use_expln:
            # From gSDE paper, it allows to keep variance
            # above zero and prevent it from growing too fast
            below_threshold = th.exp(self.log_std) * (self.log_std <= 0)
            # Avoid NaN: zeros values that are below zero
            self.safe_log_std = self.log_std * (self.log_std > 0) + self.epsilon
            above_threshold = (th.log1p(self.safe_log_std) + 1.0) * (self.log_std > 0)
            std = below_threshold + above_threshold
        else:
            # Use normal exponential
            std = th.exp(self.log_std)

        if self.full_std:
            return std
        assert self.latent_sde_dim is not None
        # Reduce the number of parameters:
        return th.ones(self.latent_sde_dim, self.action_dim).to(self.log_std.device) * std



    def sample_weights(self, batch_size: int = 1)-> th.Tensor:
      """
      Sample weights for the noise exploration matrix,
      using a centered Gaussian distribution.

      :param log_std:
      :param batch_size:
      """
      std = self.get_std()
      self.weights_dist = Normal(th.zeros_like(std), std)
      # Reparametrization trick to pass gradients
      self.exploration_mat = self.weights_dist.rsample()
      # Pre-compute matrices in case of parallel exploration
      exploration_matrices = self.weights_dist.rsample((batch_size,))
      return exploration_matrices

    def get_noise(self, batch_size: int = 1) -> th.Tensor:
        self.exploration_matrices = self.sample_weights()
        self._latent_sde = self._latent_sde if self.learn_features else self._latent_sde.detach()
        if len(self._latent_sde) == 1 or len(self._latent_sde) != len(self.exploration_matrices):
            return th.mm(self._latent_sde, self.exploration_mat)
        self._latent_sde = self._latent_sde.unsqueeze(dim=1)
        noise = th.bmm(self._latent_sde, self.exploration_matrices)
        return noise.squeeze(dim=1)


    def proba_distribution(
        self, mean_actions: th.Tensor) -> th.Tensor:
        """
        Create the distribution given its parameters (mean, std)

        :param mean_actions:
        :param log_std:
        :param latent_sde:
        :return:
        """
        # Stop gradient if we don't want to influence the features
        self._latent_sde = self._latent_sde if self.learn_features else self._latent_sde.detach()
        variance = th.mm(self._latent_sde**2, self.get_std(self.log_std) ** 2)
        distribution = Normal(mean_actions, th.sqrt(variance + self.epsilon))
        return distribution

    #get action
    def sample(self) -> th.Tensor:
        noise = self.get_noise()
        self.distribution = proba_distribution(self.mean_actions, self.log_std)
        actions = self.distribution.mean + noise
        if self.bijector is not None:
            return self.bijector.forward(actions)
        return actions

# --------------------------------------------- logprobs and entropy --------------------------------------------
#to be both called after self.sample, otherwise self.distribution wuold be Nan and you get nothing

    def log_prob(self, actions: th.Tensor) -> th.Tensor:
        if self.bijector is not None:
            gaussian_actions = self.bijector.inverse(actions)
        else:
            gaussian_actions = actions
        # log likelihood for a gaussian
        log_prob = self.distribution.log_prob(gaussian_actions)
        # Sum along action dim
        log_prob = sum_independent_dims(log_prob)

        if self.bijector is not None:
            # Squash correction (from original SAC implementation)
            log_prob -= th.sum(self.bijector.log_prob_correction(gaussian_actions), dim=1)
        return log_prob

    def entropy(self) -> Optional[th.Tensor]:
        if self.bijector is not None:
            # No analytical form,
            # entropy needs to be estimated using -log_prob.mean()
            return None
        return sum_independent_dims(self.distribution.entropy())


# ---------------------------------------------- auxiliary functions  ------------------------------------------------
#not stricly needed for my PPO. Might still be useful, so keep them
    def mode(self) -> th.Tensor:
        actions = self.distribution.mean
        if self.bijector is not None:
            return self.bijector.forward(actions)
        return actions

    def actions_from_params(
        self, mean_actions: th.Tensor, deterministic: bool = False
    ) -> th.Tensor:
        # Update the proba distribution
        self.proba_distribution(mean_actions, self.log_std)
        return self.get_actions(deterministic=deterministic)

    def log_prob_from_params(
        self, mean_actions: th.Tensor) -> Tuple[th.Tensor, th.Tensor]:
        actions = self.actions_from_params(mean_actions)
        log_prob = self.log_prob(actions)
        return actions, log_prob

    def proba_distribution_net(self):
        pass
