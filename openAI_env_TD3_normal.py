"""
td3 using the env observation, just to test if everything is ok with td3
"""

import gym
import copy
import numpy as np
import matplotlib.pyplot as plt

import torch
import torch.optim as optim
import torch.nn.functional as F

from networks_architectures import Actor, Critic, SpecialCritic
from memory_utilities import MemoryClass

if torch.cuda.is_available():
    device = torch.device('cuda')
    print("Working with GPU")
else:
    device = torch.device('cpu')
    print("Working with CPU")

class TD3Agent:
    def __init__(self):
        self.device = device

        # -------- Hyper-parameters --------------- #
        self.batch_size = 32
        self.minimal_buffer_size = 256

        self.gamma      = 0.99
        self.tau        = 0.005
        self.update_counter     = 0
        self.policy_freq_update = 2
        self.max_memory_size    = 10_000

        self.memory = MemoryClass(self.max_memory_size)

        self.num_action = 1
        self.z_in_size  = 3  # this is the obs space vector size

        self.lr_actor   = 1e-4
        self.lr_critic  = 1e-3

        # ---- Initialization Models --- #
        self.special_critic = SpecialCritic(self.z_in_size, self.num_action).to(self.device)
        self.actor          = Actor(self.z_in_size,  self.num_action).to(self.device)

        self.actor_target           = copy.deepcopy(self.actor)
        self.special_critic_target = copy.deepcopy(self.special_critic)

        self.actor_optimizer          = optim.Adam(self.actor.parameters(),          lr=self.lr_actor)
        self.special_critic_optimizer = optim.Adam(self.special_critic.parameters(), lr=self.lr_critic)

        self.G = 10  # internal loop for Policy update

    def update_function(self):
        self.policy_learning_function()

    def policy_learning_function(self):
        if len(self.memory.memory_buffer_experiences) <= self.minimal_buffer_size:
            return
        else:
            self.actor.train()
            self.special_critic.train()

            for it in range(1, self.G + 1):
                self.update_counter += 1  # this is used for delay/

                states, actions, rewards, next_states, dones = self.memory.sample_frame_vector_experiences(self.batch_size)
                states, actions, rewards, next_states, dones = self.prepare_tensor(states, actions, rewards, next_states, dones)

                with torch.no_grad():
                    next_actions = self.actor_target(next_states)
                    target_noise = 0.2 * torch.randn_like(next_actions)
                    target_noise = target_noise.clamp_(-0.5, 0.5)
                    next_actions = next_actions + target_noise
                    next_actions = next_actions.clamp_(-2, 2)

                    next_q_values_q1, next_q_values_q2 = self.special_critic_target.forward(next_states, next_actions)
                    q_min = torch.minimum(next_q_values_q1, next_q_values_q2)

                    q_target = rewards + (self.gamma * (1 - dones) * q_min)

                q_vals_q1, q_vals_q2 = self.special_critic.forward(states, actions)

                critic_loss_1 = F.mse_loss(q_vals_q1, q_target)
                critic_loss_2 = F.mse_loss(q_vals_q2, q_target)
                critic_loss_total = critic_loss_1 + critic_loss_2

                self.special_critic_optimizer.zero_grad()
                critic_loss_total.backward()
                self.special_critic_optimizer.step()


                if self.update_counter % self.policy_freq_update == 0:
                    # ------- calculate the actor loss
                    actor_q1, actor_q2 = self.special_critic.forward(states, self.actor.forward(states))

                    actor_q_min = torch.minimum(actor_q1, actor_q2)
                    actor_loss  = - actor_q_min.mean()

                    self.actor_optimizer.zero_grad()
                    actor_loss.backward()
                    self.actor_optimizer.step()

                    # ------------------------------------- Update target networks --------------- #
                    for target_param, param in zip(self.actor_target.parameters(), self.actor.parameters()):
                        target_param.data.copy_(param.data * self.tau + target_param.data * (1.0 - self.tau))

                    for target_param, param in zip(self.special_critic_target.parameters(), self.special_critic.parameters()):
                        target_param.data.copy_(param.data * self.tau + target_param.data * (1.0 - self.tau))


    def get_action_from_policy(self, state):
        state_tensor  = torch.FloatTensor(state)
        state_tensor  = state_tensor.unsqueeze(0)
        state_tensor  = state_tensor.to(self.device)

        #self.actor.eval()
        with torch.no_grad():
            action = self.actor.forward(state_tensor)
            action = action.cpu().data.numpy()
        return action[0]


    def prepare_tensor(self, states, actions, rewards, next_states, dones):
        states  = np.array(states)
        actions = np.array(actions)
        rewards = np.array(rewards).reshape(-1, 1)
        dones   = np.array(dones).reshape(-1, 1)
        next_states = np.array(next_states)

        states  = torch.FloatTensor(states).to(self.device)
        actions = torch.FloatTensor(actions).to(self.device)
        rewards = torch.FloatTensor(rewards).to(self.device)
        dones   = torch.FloatTensor(dones).to(self.device)
        next_states = torch.FloatTensor(next_states).to(self.device)

        return states, actions, rewards, next_states, dones

    def plot_functions(self, rewards):
        plt.title("Rewards")
        plt.plot(rewards)
        plt.savefig(f"plot_results/td3_pendulum_curves_.png")


def run_training_rl_method(env, agent, num_episodes_training=100, episode_horizont=200):
    rewards = []

    for episode in range(1, num_episodes_training + 1):
        print(f"-----------------Episode {episode}-----------------------------")
        episode_reward = 0
        state = env.reset()

        for step in range(1, episode_horizont + 1):
            action = agent.get_action_from_policy(state)
            noise = np.random.normal(0, scale=0.1, size=1)
            action = action + noise
            action = np.clip(action, -2, 2)

            new_state, reward, done, _ = env.step(action)
            agent.memory.save_frame_vector_experience_buffer(state, action, reward, new_state, done)
            state = new_state

            episode_reward += reward

            if done:
                break

            agent.update_function()

        rewards.append(episode_reward)
        print(f"Episode {episode} End, Total reward: {episode_reward}")
        if episode % 50 == 0:
            agent.plot_functions(rewards)

    agent.plot_functions(rewards)



def run_exploration(env, agent,  num_exploration_episodes, episode_horizont):
    print("exploration start")
    for episode in range(1, num_exploration_episodes + 1):
        state = env.reset()
        for step in range(1, episode_horizont):
            action = env.action_space.sample()
            new_state, reward, done, _ = env.step(action)
            agent.memory.save_frame_vector_experience_buffer(state, action, reward, new_state, done)
            state = new_state
            if done:
                break
    print("exploration end")


def main_run():
    env = gym.make('Pendulum-v1')
    agent = TD3Agent()
    num_episodes_exploration  = 200
    num_episodes_training     = 1000
    episode_horizont          = 200

    run_exploration(env, agent, num_episodes_exploration, episode_horizont)
    run_training_rl_method(env, agent, num_episodes_training, episode_horizont)

    env.close()


if __name__ == '__main__':
    main_run()