# -*- coding: utf-8 -*-
"""gSDE_class.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/14-PmUmqjlT_F3frLO4-ootagzOeJ1EZS
"""

from typing import Any, Dict, List, Optional, Tuple, TypeVar, Union

import numpy as np
import torch as th
from gymnasium import spaces
from torch import nn

from stable_baselines3.common.distributions import Distribution

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

## Needed class for gSDE 🎡
The **TanhBijector** class defines a bijective transformation using the hyperbolic tangent function (tanh). This class is often used in reinforcement learning algorithms to squash the output of the policy network to ensure that the actions remain within a specific range, typically [-1,1]
"""

class TanhBijector:
    """
    Bijective transformation of a probability distribution
    using a squashing function (tanh)

    :param epsilon: small value to avoid NaN due to numerical imprecision.
    """

    def __init__(self, epsilon: float = 1e-6):
        super().__init__()
        self.epsilon = epsilon

    @staticmethod
    def forward(x: th.Tensor) -> th.Tensor:
        return th.tanh(x)

    @staticmethod
    def atanh(x: th.Tensor) -> th.Tensor:
        """
        Inverse of Tanh

        Taken from Pyro: https://github.com/pyro-ppl/pyro
        0.5 * torch.log((1 + x ) / (1 - x))
        """
        return 0.5 * (x.log1p() - (-x).log1p())

    @staticmethod
    def inverse(y: th.Tensor) -> th.Tensor:
        """
        Inverse tanh.

        :param y:
        :return:
        """
        eps = th.finfo(y.dtype).eps
        # Clip the action to avoid NaN
        return TanhBijector.atanh(y.clamp(min=-1.0 + eps, max=1.0 - eps))

    def log_prob_correction(self, x: th.Tensor) -> th.Tensor:
        # Squash correction (from original SAC implementation)
        return th.log(1.0 - th.tanh(x) ** 2 + self.epsilon)

"""## gSDE class 🐧"""

class gSDE(Distribution):
    bijector: Optional["TanhBijector"]
    latent_sde_dim: Optional[int]
    weights_dist: Normal
    _latent_sde: th.Tensor
    exploration_mat: th.Tensor
    exploration_matrices: th.Tensor

    def __init__(
        self,
        action_dim: int,
        full_std: bool = True,
        use_expln: bool = False,
        squash_output: bool = False,
        learn_features: bool = False,
        epsilon: float = 1e-6,
    ):
        super().__init__()
        self.action_dim = action_dim
        self.latent_sde_dim = None
        self.mean_actions = None #get from nn
        self.log_std = None #get from NN
        self.use_expln = use_expln
        self.full_std = full_std
        self.epsilon = epsilon
        self.learn_features = learn_features
        if squash_output:
            self.bijector = TanhBijector(epsilon)
        else:
            self.bijector = None

    #-------------------------------------------- get actions ------------------------------------------------------
    def get_std(self, log_std: th.Tensor) -> th.Tensor:
        """
        Get the standard deviation from the learned parameter
        (log of it by default). This ensures that the std is positive.

        :param log_std:
        :return:
        """
        if self.use_expln:
            # From gSDE paper, it allows to keep variance
            # above zero and prevent it from growing too fast
            below_threshold = th.exp(log_std) * (log_std <= 0)
            # Avoid NaN: zeros values that are below zero
            safe_log_std = log_std * (log_std > 0) + self.epsilon
            above_threshold = (th.log1p(safe_log_std) + 1.0) * (log_std > 0)
            std = below_threshold + above_threshold
        else:
            # Use normal exponential
            std = th.exp(log_std)

        if self.full_std:
            return std
        assert self.latent_sde_dim is not None
        # Reduce the number of parameters:
        return th.ones(self.latent_sde_dim, self.action_dim).to(log_std.device) * std



    def sample_weights(self, log_std: th.Tensor, batch_size: int = 1)-> th.Tensor:
      """
      Sample weights for the noise exploration matrix,
      using a centered Gaussian distribution.

      :param log_std:
      :param batch_size:
      """
      std = self.get_std(log_std)
      self.weights_dist = Normal(th.zeros_like(std), std)
      # Reparametrization trick to pass gradients
      self.exploration_mat = self.weights_dist.rsample()
      # Pre-compute matrices in case of parallel exploration
      exploration_matrices = self.weights_dist.rsample((batch_size,))
      return exploration_matrices

    def get_noise(self, latent_sde: th.Tensor) -> th.Tensor:
        self.exploration_matrices = self.sample_weights(log_std)
        latent_sde = latent_sde if self.learn_features else latent_sde.detach()
        # Default case: only one exploration matrix
        if len(latent_sde) == 1 or len(latent_sde) != len(self.exploration_matrices):
            return th.mm(latent_sde, self.exploration_mat)
        # Use batch matrix multiplication for efficient computation
        # (batch_size, n_features) -> (batch_size, 1, n_features)
        latent_sde = latent_sde.unsqueeze(dim=1)
        # (batch_size, 1, n_actions)
        noise = th.bmm(latent_sde, self.exploration_matrices)
        return noise.squeeze(dim=1)


    def get_distribution(
        self: gSDE, mean_actions: th.Tensor, log_std: th.Tensor, latent_sde: th.Tensor
    ) -> th.Tensor:
        """
        Create the distribution given its parameters (mean, std)

        :param mean_actions:
        :param log_std:
        :param latent_sde:
        :return:
        """
        # Stop gradient if we don't want to influence the features
        self._latent_sde = latent_sde if self.learn_features else latent_sde.detach()
        variance = th.mm(self._latent_sde**2, self.get_std(log_std) ** 2)
        distribution = Normal(mean_actions, th.sqrt(variance + self.epsilon))
        return distribution

    #get action
    def sample(self) -> th.Tensor:
        noise = self.get_noise(self._latent_sde)
        self.distribution = get_distribution(self.mean_actions, self.log_std, latent_sde)
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
        self, mean_actions: th.Tensor, log_std: th.Tensor, latent_sde: th.Tensor, deterministic: bool = False
    ) -> th.Tensor:
        # Update the proba distribution
        self.proba_distribution(mean_actions, log_std, latent_sde)
        return self.get_actions(deterministic=deterministic)

    def log_prob_from_params(
        self, mean_actions: th.Tensor, log_std: th.Tensor, latent_sde: th.Tensor
    ) -> Tuple[th.Tensor, th.Tensor]:
        actions = self.actions_from_params(mean_actions, log_std, latent_sde)
        log_prob = self.log_prob(actions)
        return actions, log_prob